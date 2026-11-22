"""Adapters: one way to talk to the real system under test, whatever it is.

  python  an in-process class with handle(user, session, text) (or a function)
  http    a chat endpoint; its tools are pointed at our fake-tools server
  cli     a process that reads messages on stdin and answers on stdout

All three give the driver the same thing back: a list of reply strings, or an error string.
"""
import inspect
import json
import os
import queue
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from .tools import ToolServer, load_module
from .world import SpecError


class TargetError(Exception):
    pass


def _replies(out):
    """Normalise whatever the target returned into a list of strings."""
    if out is None:
        return []
    if isinstance(out, str):
        return [out] if out.strip() else []
    if isinstance(out, dict):
        for k in ("replies", "messages", "reply", "text", "message", "response", "output"):
            if k in out:
                return _replies(out[k])
        return [json.dumps(out)]
    if isinstance(out, (list, tuple)):
        res = []
        for x in out:
            res.extend(_replies(x) if not isinstance(x, str) else ([x] if x.strip() else []))
        return res
    return [str(out)]


def _subst(v, mapping):
    if isinstance(v, str):
        for k, val in mapping.items():
            v = v.replace("{" + k + "}", str(val))
        return v
    if isinstance(v, list):
        return [_subst(x, mapping) for x in v]
    if isinstance(v, dict):
        return {k: _subst(x, mapping) for k, x in v.items()}
    return v


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def port_in_use(port, host="127.0.0.1"):
    """Is something already listening on this port? Asked the way a server would find out: by
    trying to bind it (with SO_REUSEADDR, as servers do, so a port in TIME_WAIT counts as free)."""
    s = socket.socket()
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, int(port)))
        return False
    except OSError:
        return True
    finally:
        s.close()


def pick_port(fixed=None, port_range=None, taken=()):
    """The port a target (or the fake-tools server) is given: a fixed one ("port": 8123), the first
    free one in a range ("port_range": [8100, 8199]), or any free port."""
    if fixed:
        return int(fixed)
    if port_range:
        try:
            lo, hi = int(port_range[0]), int(port_range[1])
        except (TypeError, ValueError, IndexError):
            raise SpecError("target port_range must be two numbers, e.g. [8100, 8199]") from None
        for p in range(lo, hi + 1):
            if p not in taken and not port_in_use(p):
                return p
        raise SpecError(f"no free port between {lo} and {hi} (target port_range)")
    return _free_port()


def _url_port(url):
    try:
        from urllib.parse import urlsplit
        u = urlsplit(url)
        if u.hostname in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
            return u.port
    except ValueError:
        pass
    return None


class _Alarm:
    """Per-message time limit for in-process targets (main thread, POSIX only)."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.on = bool(seconds) and hasattr(signal, "setitimer") and \
            threading.current_thread() is threading.main_thread()

    def __enter__(self):
        if self.on:
            def boom(*_):
                raise TargetError(f"no answer within {self.seconds}s")
            self.old = signal.signal(signal.SIGALRM, boom)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)

    def __exit__(self, *exc):
        if self.on:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.old)
        return False


class PythonAdapter:
    kind = "python"

    def __init__(self, cfg, root):
        entry = cfg.get("entry", "")
        if ":" not in entry:
            raise SpecError("python target needs entry 'path/to/file.py:ClassOrFunction'")
        path, self.attr = entry.rsplit(":", 1)
        self.path = path if os.path.isabs(path) else os.path.join(root, path)
        self.extra = [os.path.join(root, p) if not os.path.isabs(p) else p for p in cfg.get("pythonpath", [])]
        self.timeout = cfg.get("timeout", 20)
        self.obj = None
        self.fn = None
        self.tools = None
        self._factory = None

    def _load(self):
        mod = load_module(self.path, self.extra)
        if not hasattr(mod, self.attr):
            raise SpecError(f"{self.path} has no '{self.attr}'")
        self._factory = getattr(mod, self.attr)

    def new_instance(self, toolbox):
        if self._factory is None:
            self._load()
        self.tools = toolbox
        f = self._factory
        if inspect.isclass(f):
            params = [p for p in inspect.signature(f).parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)]
            self.obj = f(toolbox) if params else f()
            if not params:
                self.obj.tools = toolbox
            if not callable(getattr(self.obj, "handle", None)):
                raise SpecError(f"{self.attr} needs a handle(user, session, text) method")
            self.fn = None
        else:
            self.fn = f

    def send(self, user, session, text):
        try:
            with _Alarm(self.timeout):
                if self.fn is not None:
                    out = self.fn(user, session, text, self.tools)
                else:
                    out = self.obj.handle(user, session, text)
            return _replies(out), None
        except Exception as e:  # a crash in the target is a finding, not a harness failure
            return [], f"{type(e).__name__}: {e}"

    def close_session(self, user, session):
        fn = getattr(self.obj, "close", None) if self.obj is not None else None
        if callable(fn):
            try:
                fn(user, session)
            except Exception:
                pass

    def shutdown(self):
        pass


class _Process:
    def __init__(self, command, env, cwd):
        if not isinstance(command, list) or not command:
            raise SpecError("the target's command must be a non-empty list, e.g. [\"python3\", \"server.py\"]")
        # Its own process group: launchers and shell wrappers start children, and all of them
        # must go when the target is stopped, or they keep the port and the output pipes.
        kw = {"start_new_session": True} if os.name == "posix" else {}
        try:
            self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env, cwd=cwd, text=True, bufsize=1, **kw)
        except OSError as e:
            raise SpecError(f"could not start the target ({' '.join(map(str, command))}): {e}") from None
        self.pgid = self.proc.pid if kw else None
        self.lines = queue.Queue()
        self.err = []
        self._threads = [threading.Thread(target=self._pump, daemon=True),
                         threading.Thread(target=self._pump_err, daemon=True)]
        for t in self._threads:
            t.start()

    def _pump(self):
        try:
            for line in self.proc.stdout:
                self.lines.put(line.rstrip("\n"))
        except (ValueError, OSError):
            pass  # pipe closed under us at shutdown
        finally:
            self.lines.put(None)

    def _pump_err(self):
        try:
            for line in self.proc.stderr:
                self.err.append(line.rstrip("\n"))
                del self.err[:-20]
        except (ValueError, OSError):
            pass

    def write(self, line):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def read(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise TargetError(f"no answer within {timeout}s") from None
        if line is None:
            tail = " | ".join(self.err[-3:])
            raise TargetError(f"process exited (code {self.proc.poll()}) {tail}".strip())
        return line

    def _signal(self, sig):
        try:
            if self.pgid is not None:
                os.killpg(self.pgid, sig)  # the whole group: the command and everything it started
            elif self.proc.poll() is None:
                self.proc.send_signal(sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _group_alive(self):
        """Is any process of the target's group still running? A killed process that only waits to
        be reaped (a zombie) holds no port and no pipe, so it does not count."""
        if self.pgid is None:
            return self.proc.poll() is None
        try:
            os.killpg(self.pgid, 0)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        try:
            pids = [d for d in os.listdir("/proc") if d.isdigit()]
        except OSError:
            return True   # no /proc (macOS): the signal test above is all there is
        for pid in pids:
            try:
                with open(f"/proc/{pid}/stat") as f:
                    rest = f.read().rsplit(")", 1)[1].split()   # state, ppid, pgrp, ...
            except (OSError, IndexError):
                continue
            if len(rest) > 2 and rest[2] == str(self.pgid) and rest[0] not in ("Z", "X"):
                return True
        return False

    def kill(self, grace=0.3):
        """Stop the command and every process it started. Never blocks on output pipes that an
        orphaned child might still hold open."""
        self._signal(signal.SIGTERM)
        deadline = time.time() + grace
        while time.time() < deadline and self.proc.poll() is None:
            time.sleep(0.01)
        self._signal(getattr(signal, "SIGKILL", signal.SIGTERM))
        try:
            self.proc.wait(timeout=5)
        except Exception:
            pass
        deadline = time.time() + 2
        while time.time() < deadline and self._group_alive():
            self.proc.poll()
            time.sleep(0.01)
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        # stdout/stderr are read by daemon threads, which end when the last holder of the pipe
        # exits. Closing a pipe that a thread is still blocked on would block here too (that was
        # the hang with orphaned children), so they are closed only once the readers are done.
        for t, f in zip(self._threads, (self.proc.stdout, self.proc.stderr)):
            t.join(timeout=1)
            if not t.is_alive():
                try:
                    f.close()
                except Exception:
                    pass


class _External:
    """Shared by http and cli: owns the fake-tools server that the target is pointed at."""

    def __init__(self, cfg, root):
        self.cfg, self.root = cfg, root
        self.timeout = cfg.get("timeout", 30)
        rng = cfg.get("port_range")
        tools_port = int(cfg.get("tools_port", 0)) or (pick_port(None, rng) if rng else 0)
        self.server = ToolServer(None, port=tools_port, headers=cfg.get("attribution_headers"))
        try:
            port = pick_port(cfg.get("port"), rng, taken=(self.server.port,))
        except SpecError:
            self.server.close()
            raise
        self.vars = {"tools_url": self.server.url, "tools_port": self.server.port, "port": port, "root": root}

    def env(self, extra=None):
        env = dict(os.environ)
        env["POPTEST_TOOLS_URL"] = self.server.url
        env.update({k: str(v) for k, v in _subst(self.cfg.get("env", {}), self.vars).items()})
        env.update(extra or {})
        return env

    def cwd(self):
        return os.path.join(self.root, self.cfg["cwd"]) if self.cfg.get("cwd") else self.root


class HTTPAdapter(_External):
    kind = "http"

    def __init__(self, cfg, root):
        super().__init__(cfg, root)
        if not cfg.get("url"):
            raise SpecError("http target needs 'url'")
        self.url = _subst(cfg["url"], self.vars)
        self.proc = None

    def _start(self):
        st = self.cfg.get("start")
        if not st:
            return
        if not isinstance(st, dict) or not st.get("command"):
            raise SpecError("http target 'start' needs a 'command' list")
        ready = _subst(st.get("ready_url", self.url), self.vars)
        port = _url_port(self.url)
        if port:
            # A fixed port is only usable once the previous process (and its children) let go of it.
            deadline = time.time() + float(st.get("port_wait", 5))
            while port_in_use(port) and time.time() < deadline:
                time.sleep(0.05)
            if port_in_use(port):
                raise SpecError(f"port {port} is already in use, so the target cannot be started on it. "
                                f"Another process is listening there (an earlier target that was not stopped, "
                                f"or someone else's service). Stop it, or set another 'port' / 'port_range' "
                                f"in the target config.")
        self.proc = _Process(_subst(st["command"], self.vars), self.env(_subst(st.get("env", {}), self.vars)),
                             self.cwd())
        # Ready = the readiness URL answers with a status the config accepts. By default any status
        # below 500: a 404/405 on a chat route means the server is up, a 502/503 means a proxy or
        # launcher is up but the service behind it is not.
        accept = st.get("ready_status")
        if isinstance(accept, int):
            accept = [accept]
        timeout = st.get("ready_timeout", 15)
        deadline = time.time() + timeout
        last = "no answer"
        while time.time() < deadline:
            if self.proc.proc.poll() is not None:
                time.sleep(0.05)
                err = " | ".join(self.proc.err[-5:]) or f"exit code {self.proc.proc.poll()}"
                self.proc.kill()
                self.proc = None
                raise SpecError("target process exited at start: " + err)
            try:
                with urllib.request.urlopen(ready, timeout=1) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
                e.close()
            except Exception as e:
                last = f"{type(e).__name__}"
                time.sleep(0.05)
                continue
            if (code in accept) if accept else (code < 500):
                return
            last = f"HTTP {code}"
            time.sleep(0.05)
        self.proc.kill()
        self.proc = None
        raise SpecError(f"target did not become ready at {ready} within {timeout}s (last answer: {last})")

    def new_instance(self, toolbox):
        self.server.toolbox = toolbox
        reset = self.cfg.get("reset", "restart" if self.cfg.get("start") else None)
        if self.proc is None:
            self._start()
        elif reset == "restart":
            self.proc.kill()
            self._start()
        if isinstance(reset, dict):
            req = urllib.request.Request(_subst(reset["url"], self.vars), b"{}",
                                         {"Content-Type": "application/json"}, method=reset.get("method", "POST"))
            try:
                urllib.request.urlopen(req, timeout=self.timeout).close()
            except Exception as e:
                raise SpecError(f"could not reset the target: {e}") from None

    def send(self, user, session, text):
        m = {"user": user, "session": session, "text": text}
        tmpl = self.cfg.get("request", {"user": "{user}", "session": "{session}", "text": "{text}"})
        body = json.dumps(_fill(tmpl, m)).encode()
        headers = {"Content-Type": "application/json", "X-Poptest-Traffic": "synthetic"}
        headers.update(_subst(self.cfg.get("headers", {}), dict(self.vars, **m)))
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url, body, headers), timeout=self.timeout) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return [], f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}"
        except Exception as e:
            return [], f"{type(e).__name__}: {e}"
        try:
            data = json.loads(raw)
        except ValueError:
            return _replies(raw), None
        path = self.cfg.get("reply_path")
        if path:
            for part in path.split("."):
                data = data[int(part)] if isinstance(data, list) else (data or {}).get(part)
        return _replies(data), None

    def close_session(self, user, session):
        pass

    def shutdown(self):
        if self.proc:
            self.proc.kill()
        self.server.close()


def _fill(tmpl, m):
    """Fill a request template; values are substituted as data (no string surgery on JSON)."""
    if isinstance(tmpl, str):
        if tmpl in ("{user}", "{session}", "{text}"):
            return m[tmpl[1:-1]]
        return _subst(tmpl, m)
    if isinstance(tmpl, list):
        return [_fill(x, m) for x in tmpl]
    if isinstance(tmpl, dict):
        return {k: _fill(v, m) for k, v in tmpl.items()}
    return tmpl


class CLIAdapter(_External):
    """protocol 'jsonl': one JSON object per line in ({"user","session","text"}), one line out
    ({"replies": [...]} or plain text). protocol 'text': the message as one line in; one line out,
    or lines up to `end_marker`. scope 'instance' = one process for everything; 'session' = one
    process per session (command may use {user} and {session})."""
    kind = "cli"

    def __init__(self, cfg, root):
        super().__init__(cfg, root)
        if not cfg.get("command"):
            raise SpecError("cli target needs 'command' (a list)")
        self.protocol = cfg.get("protocol", "jsonl")
        self.scope = cfg.get("scope", "instance" if self.protocol == "jsonl" else "session")
        self.procs = {}

    def new_instance(self, toolbox):
        self.server.toolbox = toolbox
        self._kill_all()

    def _kill_all(self):
        for p in self.procs.values():
            p.kill()
        self.procs = {}

    def _proc(self, user, session):
        key = session if self.scope == "session" else "*"
        p = self.procs.get(key)
        if p is None or p.proc.poll() is not None:
            m = dict(self.vars, user=user, session=session)
            p = _Process(_subst(self.cfg["command"], m),
                         self.env({"POPTEST_USER": str(user), "POPTEST_SESSION": str(session)}), self.cwd())
            self.procs[key] = p
        return p

    def send(self, user, session, text):
        try:
            p = self._proc(user, session)
            if self.protocol == "jsonl":
                p.write(json.dumps({"user": user, "session": session, "text": text}))
                line = p.read(self.timeout)
                try:
                    return _replies(json.loads(line)), None
                except ValueError:
                    return _replies(line), None
            p.write(text.replace("\n", " "))
            marker = self.cfg.get("end_marker")
            if marker is None:
                return _replies(p.read(self.timeout)), None
            lines = []
            while True:
                line = p.read(self.timeout)
                if line.strip() == marker:
                    break
                lines.append(line)
            return _replies("\n".join(lines)), None
        except (TargetError, OSError) as e:
            return [], str(e)

    def close_session(self, user, session):
        if self.scope == "session" and session in self.procs:
            self.procs.pop(session).kill()

    def shutdown(self):
        self._kill_all()
        self.server.close()


def make_adapter(cfg, root):
    kind = cfg.get("adapter", "python")
    if kind == "python":
        return PythonAdapter(cfg, root)
    if kind == "http":
        return HTTPAdapter(cfg, root)
    if kind == "cli":
        return CLIAdapter(cfg, root)
    raise SpecError(f"unknown adapter {kind!r} (use python, http or cli)")
