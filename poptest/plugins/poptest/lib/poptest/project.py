"""A poptest project: a folder with poptest.json and the files it points to."""
import glob
import json
import os

from . import vocab as vocab_mod
from .tools import load_handlers, load_module
from .world import SpecError, World

CONFIG = "poptest.json"
FAMILIES = ["happy_path", "boundary", "mind_change", "negated_phrasing", "wrong_id", "split_messages",
            "topic_switch", "cross_user", "cross_session", "concurrent_sessions", "clock", "permissions",
            "record_detail_leak", "messy_input", "repeat_action"]


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise SpecError(f"file not found: {path}") from None
    except json.JSONDecodeError as e:
        raise SpecError(f"{path}: not valid JSON (line {e.lineno}: {e.msg})") from None


def find_root(start="."):
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, CONFIG)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise SpecError(f"no {CONFIG} here or in any parent folder. Run 'poptest init' first, "
                            f"or pass --project DIR.")
        d = parent


class Project:
    def __init__(self, root="."):
        self.root = find_root(root)
        self.config = read_json(os.path.join(self.root, CONFIG))
        c = self.config
        self.name = c.get("name", os.path.basename(self.root))
        self.seed = int(c.get("seed", 7))
        self.world_spec = read_json(self.path(c.get("world", "world.json")))
        self.tools_spec = read_json(self.path(c.get("tools", "tools.json")))
        self.handlers = load_handlers(self.tools_spec, os.path.dirname(self.path(c.get("tools", "tools.json"))))
        rules_path = self.path(c.get("rules", "rules.json"))
        self.rules = read_json(rules_path) if os.path.exists(rules_path) else {}
        self.rules_module = None
        if self.rules.get("python"):
            self.rules_module = load_module(os.path.join(os.path.dirname(rules_path), self.rules["python"]))
        vpath = self.path(c.get("vocab", "vocab.json"))
        self.vocab = vocab_mod.merge(vocab_mod.DEFAULT, read_json(vpath) if os.path.exists(vpath) else None)
        ppath = self.path(c.get("population", "population.json"))
        self.population = read_json(ppath) if os.path.exists(ppath) else None
        self._snap = {}
        for key, val in (("world", self.world_spec), ("tools", self.tools_spec), ("rules", self.rules)):
            if not isinstance(val, dict):
                raise SpecError(f"{c.get(key, key + '.json')} must contain a JSON object")
        if self.population is not None and not isinstance(self.population, dict):
            raise SpecError(f"{c.get('population', 'population.json')} must contain a JSON object")
        if not isinstance(self.rules.get("actions", {}), dict):
            raise SpecError("rules.json 'actions' must be an object: {\"<tool or action name>\": {...}}")
        tools = self.tools_spec.get("tools", {})
        for name, act in self.rules.get("actions", {}).items():
            if not isinstance(act, dict):
                raise SpecError(f"rules.json actions: '{name}' must be an object")
            tool = act.get("tool", name)
            if tool not in tools:
                raise SpecError(
                    f"rules.json actions: '{name}' is not a tool in tools.json"
                    + (f" (its \"tool\" is {tool!r})" if "tool" in act else
                       ". Name the tool with \"tool\": \"<tool>\" (and a \"when\" condition on its arguments) "
                       "if this entry describes one kind of use of a shared tool; if it is left over from the "
                       "init template, delete it.")
                    + f" Tools: {', '.join(tools) or 'none'}.")
            if "when" in act:
                try:
                    compile(act["when"], "<when>", "eval")
                except (SyntaxError, TypeError) as e:
                    raise SpecError(f"rules.json actions: '{name}'.when is not a valid expression: "
                                    f"{getattr(e, 'msg', e)}") from None

    def path(self, rel):
        return rel if os.path.isabs(rel) else os.path.join(self.root, rel)

    # ---- world
    def base_snapshot(self, seed=None):
        seed = self.seed if seed is None else seed
        if seed not in self._snap:
            self._snap[seed] = World(self.world_spec, seed).snapshot()
        return self._snap[seed]

    def new_world(self, seed=None):
        seed = self.seed if seed is None else seed
        return World.from_snapshot(self.world_spec, self.base_snapshot(seed), seed)

    # ---- target
    def target_config(self, override=None):
        base = dict(self.config.get("target") or {})
        if not override:
            if not base:
                raise SpecError("poptest.json has no 'target'. See the connect-target skill.")
            return base
        if isinstance(override, dict):
            return override
        if override.endswith(".json"):
            cfg = read_json(self.path(override))
            return cfg.get("target", cfg)
        if override.startswith("http://") or override.startswith("https://"):
            return dict(base, adapter="http", url=override)
        if ":" in override:
            keep = {k: v for k, v in base.items() if k in ("timeout", "pythonpath")} \
                if base.get("adapter", "python") == "python" else {}
            return dict(keep, adapter="python", entry=override)
        raise SpecError(f"cannot understand target {override!r}: use file.py:Class, a URL, or a .json file")

    # ---- cases
    def load_cases(self, paths=None, only=None):
        paths = paths or [self.path(self.config.get("cases", "cases"))]
        files = []
        for p in paths:
            p = self.path(p)
            if os.path.isdir(p):
                files.extend(sorted(glob.glob(os.path.join(p, "**", "*.json"), recursive=True)))
            elif os.path.exists(p):
                files.append(p)
            else:
                raise SpecError(f"cases path not found: {p}")
        cases, seen = [], {}
        for f in files:
            raw = read_json(f)
            items = raw.get("cases", [raw]) if isinstance(raw, dict) else raw
            for c in items:
                c = normalise_case(c, f)
                if c["id"] in seen:
                    raise SpecError(f"duplicate case id {c['id']!r} in {f} and {seen[c['id']]}")
                seen[c["id"]] = f
                cases.append(c)
        if only:
            cases = [c for c in cases if any(o == c["id"] or o == c.get("family") or
                                             (o.endswith("*") and c["id"].startswith(o[:-1])) for o in only)]
        return cases


def normalise_case(c, where="case"):
    """Accepts the 'steps' form or the simpler 'sessions' form; returns the 'steps' form."""
    if not isinstance(c, dict) or not c.get("id"):
        raise SpecError(f"{where}: every case needs an 'id'")
    cid = str(c["id"])
    out = {k: v for k, v in c.items() if k not in ("sessions", "steps")}
    out["id"] = cid
    steps = []
    if "steps" in c:
        for i, s in enumerate(c["steps"]):
            if isinstance(s, str):
                s = {"say": s}
            if not isinstance(s, dict) or not ({"say", "advance", "close", "patch", "fail"} & set(s)):
                raise SpecError(f"{where}: case {cid} step {i + 1} needs one of say/advance/close/patch/fail")
            if "advance" in s and (not isinstance(s["advance"], dict) or
                                   set(s["advance"]) - {"days", "hours", "minutes"}):
                raise SpecError(f"{where}: case {cid} step {i + 1}: advance takes days, hours and/or minutes")
            if "say" in s:
                s = dict(s, session=str(s.get("session", "main")), say=str(s["say"]))
            steps.append(s)
    elif "sessions" in c:
        prev = 0
        for i, sess in enumerate(c["sessions"]):
            off = float(sess.get("day_offset", prev))
            if off != prev:
                steps.append({"advance": {"days": off - prev}})
                prev = off
            name = str(sess.get("name", f"s{i + 1}"))
            for m in sess.get("messages", []):
                st = {"session": name, "say": str(m)}
                if sess.get("user"):
                    st["user"] = sess["user"]
                steps.append(st)
            steps.append({"close": name})
    else:
        raise SpecError(f"{where}: case {cid} needs 'steps' or 'sessions'")
    out["steps"] = steps
    if not out.get("user"):
        users = [s.get("user") for s in steps if s.get("user")]
        if not users:
            raise SpecError(f"{where}: case {cid} needs a 'user'")
        out["user"] = users[0]
    return out
