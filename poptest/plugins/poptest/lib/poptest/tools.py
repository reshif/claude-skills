"""Fake tools: what the system under test is allowed to call.

Tools are declared in tools.json and implemented by small handler functions in a Python module
(`def tool_name(world, **args)`). Every call is logged with the true state before the call and
the exact changes it made, so checks never have to take the target's word for anything.

Two ways in: an in-process `ToolBox` object (tools.name(arg=...)) and a local HTTP server
(POST /call/<name>) for targets that run as a separate process.
"""
import copy
import importlib.util
import itertools
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .world import SpecError, diff

_mod_counter = itertools.count()


class ToolError(Exception):
    """An error answer from a fake tool. Raise it in tools.py for anything the real API answers
    with an error rather than a result:

        from poptest.tools import ToolError
        raise ToolError("unknown user", status=404)

    In-process targets get this exception from `tools.name(...)` (message in str(e), HTTP-style
    code in e.status). HTTP/CLI targets get that status code with the body {"error": message}.
    Default status 400; an unknown tool is 404; any other exception in a handler is a 500."""

    def __init__(self, message="", status=400):
        super().__init__(message)
        try:
            self.status = int(status)
        except (TypeError, ValueError):
            self.status = 400


def load_module(path, extra_paths=()):
    """Import a Python file under a unique name (so several copies can coexist)."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise SpecError(f"file not found: {path}")
    for p in [os.path.dirname(path), *extra_paths]:
        if p and p not in sys.path:
            sys.path.insert(0, p)
    name = f"_poptest_mod_{next(_mod_counter)}_{os.path.splitext(os.path.basename(path))[0]}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SpecError:
        raise
    except SyntaxError as e:
        raise SpecError(f"{path}: Python syntax error on line {e.lineno}: {e.msg}") from None
    except Exception as e:
        import traceback
        tb = [f for f in traceback.extract_tb(e.__traceback__) if os.path.abspath(f.filename) == path]
        where = f" (line {tb[-1].lineno})" if tb else ""
        raise SpecError(f"{path} could not be loaded{where}: {type(e).__name__}: {e}") from None
    return mod


def load_handlers(tools_spec, base_dir):
    if not isinstance(tools_spec, dict) or not isinstance(tools_spec.get("tools", {}), dict):
        raise SpecError("tools.json must be an object with a 'tools' object: {\"tools\": {\"name\": {...}}}")
    mod = load_module(os.path.join(base_dir, tools_spec.get("module", "tools.py")))
    handlers = {}
    for name, t in tools_spec.get("tools", {}).items():
        if not isinstance(t, dict):
            raise SpecError(f"tools.json: tool '{name}' must be an object")
        fn = getattr(mod, name, None)
        if not callable(fn):
            raise SpecError(f"tools.json declares '{name}' but {tools_spec.get('module', 'tools.py')} "
                            f"has no function {name}(world, ...)")
        handlers[name] = fn
    return handlers


def call_ok(result, error=None, spec=None):
    """Did a tool call succeed? Errors, {"ok": false} and {"error": ...} results count as failed,
    unless the tool is declared with "ok_from_result": false in tools.json (for tools whose
    {"ok": false} is an ordinary answer, such as verify_identity -> {"ok": false})."""
    if error:
        return False
    if spec is not None and spec.get("ok_from_result", True) is False:
        return True
    if isinstance(result, dict) and (result.get("ok") is False or result.get("error")):
        return False
    return True


class ToolBox:
    def __init__(self, world, tools_spec, handlers, emit):
        self._world = world
        self._spec = tools_spec.get("tools", {})
        self._handlers = handlers
        self._emit = emit
        self._lock = threading.RLock()
        self.context = {}  # set by the driver before every message: run, conv, session, user
        self.faults = []   # injected backend failures (case step {"fail": {...}})

    def inject_fault(self, tool, error="backend unavailable", status=503, times=1):
        """Make the next `times` calls of `tool` ("*" = any tool) fail with this error, without
        running the handler. times=None keeps failing until clear_faults()."""
        self.faults.append({"tool": tool, "error": str(error), "status": int(status), "times": times})

    def clear_faults(self, tool=None):
        self.faults = [f for f in self.faults if tool not in (None, "*") and f["tool"] != tool]

    def _fault(self, name):
        for f in self.faults:
            if f["tool"] in ("*", name):
                if f["times"] is not None:
                    f["times"] -= 1
                    if f["times"] <= 0:
                        self.faults.remove(f)
                return f
        return None

    def names(self):
        return list(self._spec)

    def describe(self):
        return {n: {"description": s.get("description", ""), "args": s.get("args", {})}
                for n, s in self._spec.items()}

    def call(self, name, args=None, context=None):
        with self._lock:
            return self._call(name, dict(args or {}), context)

    def _call(self, name, args, context):
        ctx = dict(self.context)
        ctx.update(context or {})
        w = self._world
        spec = self._spec.get(name)
        ev = dict(ctx, type="tool_call", name=name, args=copy.deepcopy(args), acting_user=ctx.get("user"),
                  t=round(w.t, 2), day=w.day)
        if spec is None:
            ev.update(result=None, error=f"unknown tool {name!r}", status=404, pre={}, changes=[])
            self._emit(ev)
            raise ToolError(ev["error"], 404)
        declared = spec.get("args", {})
        pre = {}
        for a, aspec in declared.items():
            if isinstance(aspec, dict) and aspec.get("ref") and a in args:
                pre[a] = copy.deepcopy(w.get(aspec["ref"], args[a]))
        mutates = spec.get("mutates", True)
        scope = spec.get("writes") if mutates else None
        before = None
        if mutates:
            before = {e: copy.deepcopy(w.data[e]) for e in (scope or w.data)}
        result, error, status = None, None, None
        try:
            fault = self._fault(name)
            if fault:
                ev["injected"] = True
                raise ToolError(fault["error"], fault["status"])
            unknown = [a for a in args if a not in declared] if declared else []
            if unknown:
                raise ToolError(f"{name}: unexpected argument(s) {unknown}")
            missing = [a for a, s in declared.items()
                       if isinstance(s, dict) and s.get("required", True) and a not in args]
            if missing:
                raise ToolError(f"{name}: missing argument(s) {missing}")
            result = self._handlers[name](w, **args)
            result = json.loads(json.dumps(result))  # must be plain JSON; also detaches from world
        except ToolError as e:
            error, status = str(e), e.status
        except Exception as e:  # a broken handler is reported, never swallowed
            error, status = f"{type(e).__name__}: {e}", 500
        changes = diff(before, w.data, scope or None) if mutates else []
        ev.update(result=result, error=error, pre=pre, changes=changes)
        if error:
            ev["status"] = status
        self._emit(ev)
        if error:
            raise ToolError(error, status)
        return result

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        spec = self._spec.get(name)

        def tool(*a, **kw):
            if a:
                order = list((spec or {}).get("args", {}))
                if len(a) > len(order):
                    raise ToolError(f"{name}: too many positional arguments")
                for k, v in zip(order, a):
                    kw.setdefault(k, v)
            return self.call(name, kw)
        tool.__name__ = name
        return tool


class ToolServer:
    """Local HTTP face of a ToolBox, for targets that are separate processes.

    GET  /tools            -> {"tools": {name: {description, args}}}
    GET  /clock            -> {"day": int, "date": "YYYY-MM-DD", "now": iso}
    POST /call/<name>      body: JSON object of arguments  -> {"result": ...} or 4xx {"error": ...}
    POST /call             body: {"name": ..., "args": {...}}
    Errors: ToolError(message, status) raised by a handler -> that status (default 400);
    unknown tool -> 404; any other exception in a handler -> 500.
    Headers X-Poptest-User / X-Poptest-Session attribute the call when the target handles several
    users at once; otherwise the message currently being handled is used. A product that already
    sends its own identity headers (X-User, X-Session, ...) is mapped with `headers`:
    {"user": ["X-User"], "session": ["X-Session"]} (target config key "attribution_headers").
    """

    def __init__(self, toolbox=None, port=0, host="127.0.0.1", headers=None):
        self.toolbox = toolbox
        outer = self
        names = {"user": ["X-Poptest-User"], "session": ["X-Poptest-Session"]}
        for key, extra in (headers or {}).items():
            if key not in names:
                raise SpecError(f"attribution_headers: unknown key {key!r} (use 'user' and 'session')")
            names[key] += [extra] if isinstance(extra, str) else list(extra)
        self.header_names = names

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                tb = outer.toolbox
                if tb is None:
                    return self._send(503, {"error": "no sandbox attached"})
                if self.path.rstrip("/") == "/tools":
                    return self._send(200, {"tools": tb.describe()})
                if self.path.rstrip("/") == "/clock":
                    w = tb._world
                    return self._send(200, {"day": w.day, "date": w.date(), "now": w.now(), "hour": w.hour(),
                                            "minute": w.minute(), "time": w.time(), "weekday": w.weekday()})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                tb = outer.toolbox
                if tb is None:
                    return self._send(503, {"error": "no sandbox attached"})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._send(400, {"error": "body must be JSON"})
                path = self.path.rstrip("/")
                if path == "/call":
                    name, args = body.get("name"), body.get("args") or {}
                elif path.startswith("/call/"):
                    name, args = path[len("/call/"):], body
                else:
                    return self._send(404, {"error": "not found"})
                if not isinstance(args, dict):
                    return self._send(400, {"error": "arguments must be a JSON object"})
                ctx = {}
                for key, hdrs in outer.header_names.items():
                    for h in hdrs:
                        if self.headers.get(h):
                            ctx[key] = self.headers[h]
                            break
                try:
                    self._send(200, {"result": tb.call(name, args, ctx)})
                except ToolError as e:
                    self._send(e.status if 400 <= e.status <= 599 else 400, {"error": str(e)})

        try:
            self.httpd = ThreadingHTTPServer((host, port), Handler)
        except OSError as e:
            raise SpecError(f"the fake-tools server could not listen on port {port}: {e.strerror or e}. "
                            f"Another process is using it (an earlier target still running?); stop it or "
                            f"choose another 'tools_port'.") from None
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f"http://{host}:{self.port}"
        # a short poll interval: shutdown() waits for one interval, and a run closes one server per
        # replayed conversation batch
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
