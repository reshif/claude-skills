"""Driver: talks to the real target, owns the sandbox, writes the event log.

Everything downstream (checks, replay, reports) reads only the log, one JSON object per line:
  run_start, conv_start, world_patch, session_start, user_msg, bot_msg, tool_call,
  target_error, clock, fault, noise, session_end, conv_end, run_end
Each event carries seq, run, scope (one world + one target instance), conv, session, user,
t (minutes on the injected clock) and day.

Noise replies: a target that is random by specification ("about 3% of messages get 'Sorry, could
you repeat that?'; clients should send the message again") is declared in poptest.json:
  "noise": {"replies": ["^Sorry, could you repeat that\\?$"], "max_resends": 3}
A turn whose every reply matches is recorded (bot_msg with noise=true, then a `noise` event that
lists the tool calls and data changes of that turn), the message is sent again (user_msg with
resend=true) and only the real answer takes part in the checks. A noise turn that changed data is
reported as noise_side_effect.
"""
import json
import os
import re

from .adapters import make_adapter
from .checks import Checker
from .tools import ToolBox
from .world import VERSION, SpecError, apply_patches


class EventLog:
    def __init__(self, path=None):
        self.events = []
        self.fh = None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.fh = open(path, "w", encoding="utf-8")

    def emit(self, ev):
        ev = dict(ev)
        ev["seq"] = len(self.events)
        self.events.append(ev)
        if self.fh:
            self.fh.write(json.dumps(ev, default=str) + "\n")
        return ev

    def close(self):
        if self.fh:
            self.fh.close()
            self.fh = None


def read_log(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class Noise:
    """The project's declaration of replies that are random by spec and must be retried."""

    def __init__(self, project_cfg, target_cfg):
        cfg = target_cfg.get("noise", project_cfg.get("noise")) or {}
        if isinstance(cfg, (list, str)):
            cfg = {"replies": cfg}
        if not isinstance(cfg, dict):
            raise SpecError("poptest.json 'noise' must be an object: {\"replies\": [\"pattern\", ...]}")
        pats = cfg.get("replies", [])
        pats = [pats] if isinstance(pats, str) else list(pats)
        self.patterns = []
        for p in pats:
            try:
                self.patterns.append(re.compile(p, re.I | re.S))
            except (re.error, TypeError) as e:
                raise SpecError(f"poptest.json noise.replies: {p!r} is not a valid pattern ({e})") from None
        try:
            self.max_resends = int(cfg.get("max_resends", 3))
        except (TypeError, ValueError):
            raise SpecError("poptest.json noise.max_resends must be a number") from None
        unknown = set(cfg) - {"replies", "max_resends"}
        if unknown:
            raise SpecError(f"poptest.json noise: unknown key(s) {sorted(unknown)} (use replies, max_resends)")

    def __bool__(self):
        return bool(self.patterns)

    def is_noise(self, replies):
        """A turn is noise when it has replies and every one of them matches a declared pattern."""
        return bool(self.patterns) and bool(replies) and \
            all(any(p.search(str(r)) for p in self.patterns) for r in replies)


class Scope:
    def __init__(self, sid, world, toolbox):
        self.id, self.world, self.toolbox = sid, world, toolbox


class Driver:
    def __init__(self, project, target=None, log_path=None, run_id="run", seed=None):
        self.p = project
        self.cfg = project.target_config(target)
        self.adapter = make_adapter(self.cfg, project.root)
        self.log = EventLog(log_path)
        self.run_id = run_id
        self.seed = project.seed if seed is None else seed
        self.turns = 0
        self.noise_turns = 0
        self._scopes = 0
        try:
            self.noise = Noise(project.config, self.cfg)
        except SpecError:
            self.adapter.shutdown()
            raise
        self.log.emit({"type": "run_start", "run": run_id, "project": project.name, "world_seed": self.seed,
                       "target": {k: v for k, v in self.cfg.items() if k in ("adapter", "entry", "url", "command")},
                       "poptest": VERSION})

    # ---- plumbing
    def new_scope(self, name):
        self._scopes += 1
        world = self.p.new_world(self.seed)
        toolbox = ToolBox(world, self.p.tools_spec, self.p.handlers, self.log.emit)
        self.adapter.new_instance(toolbox)
        return Scope(f"{name}", world, toolbox)

    def ctx(self, sc, conv, session=None, user=None):
        c = {"run": self.run_id, "scope": sc.id, "conv": conv, "t": round(sc.world.t, 2), "day": sc.world.day}
        if session is not None:
            c["session"] = session
        if user is not None:
            c["user"] = user
        return c

    def start_conv(self, sc, conv, kind, user, **extra):
        self.log.emit(dict(self.ctx(sc, conv, user=user), type="conv_start", kind=kind, **extra))

    def patch(self, sc, conv, patches):
        changes = apply_patches(sc.world, patches)
        if changes:
            self.log.emit(dict(self.ctx(sc, conv), type="world_patch", changes=changes))

    def open_session(self, sc, conv, sid, user):
        self.log.emit(dict(self.ctx(sc, conv, sid, user), type="session_start"))

    def say(self, sc, conv, sid, user, text, **extra):
        """Send one user message. If the answer is a declared noise reply, record it and send the
        message again (up to noise.max_resends times); the caller only sees the real answer."""
        ctx = self.ctx(sc, conv, sid, user)
        sc.toolbox.context = {k: ctx[k] for k in ("run", "scope", "conv", "session", "user")}
        self.turns += 1
        attempt = 0
        while True:
            first = len(self.log.events)
            self.log.emit(dict(ctx, type="user_msg", text=text, **(dict(extra, resend=True, attempt=attempt)
                                                                  if attempt else extra)))
            replies, err = self.adapter.send(user, sid, text)
            ctx = self.ctx(sc, conv, sid, user)
            # A "noise" reply that keeps coming back is not noise: after max_resends it is taken as
            # the system's real answer to this message and checked like any other reply.
            noisy = not err and attempt < self.noise.max_resends and self.noise.is_noise(replies)
            for r in replies:
                self.log.emit(dict(ctx, type="bot_msg", text=str(r), **({"noise": True} if noisy else {})))
            if err:
                self.log.emit(dict(ctx, type="target_error", error=err))
            if not noisy:
                return replies
            self.noise_turns += 1
            calls = [e for e in self.log.events[first:] if e["type"] == "tool_call"]
            changes = [dict(c, tool=e["name"]) for e in calls for c in (e.get("changes") or [])]
            self.log.emit(dict(ctx, type="noise", text=str(replies[0]), attempt=attempt,
                               calls=[e["name"] for e in calls], changes=changes))
            attempt += 1

    def close_session(self, sc, conv, sid, user, reason="end"):
        self.log.emit(dict(self.ctx(sc, conv, sid, user), type="session_end", reason=reason))
        self.adapter.close_session(user, sid)

    def advance(self, sc, conv, **delta):
        sc.world.advance(**delta)
        self.log.emit(dict(self.ctx(sc, conv), type="clock", advance=delta))

    def fault(self, sc, conv, spec):
        """Case step {"fail": {"tool": "make_transfer", "error": "timeout", "status": 503, "times": 1}}:
        the next call(s) of that fake tool fail as the backend would. {"fail": {"clear": true}} ends it."""
        if not isinstance(spec, dict) or not (spec.get("tool") or spec.get("clear")):
            raise SpecError("a 'fail' step needs {\"tool\": name or \"*\", \"error\": text} or {\"clear\": true}")
        if spec.get("clear"):
            sc.toolbox.clear_faults(spec.get("tool"))
        else:
            tool = spec["tool"]
            if tool != "*" and tool not in self.p.tools_spec.get("tools", {}):
                raise SpecError(f"'fail' step names unknown tool {tool!r}")
            times = spec.get("times", 1)
            sc.toolbox.inject_fault(tool, spec.get("error", "backend unavailable"), spec.get("status", 503),
                                    None if times in (None, "always") else int(times))
        self.log.emit(dict(self.ctx(sc, conv), type="fault", fault=spec))

    def end_conv(self, sc, conv, user):
        sc.toolbox.context = {}
        self.log.emit(dict(self.ctx(sc, conv, user=user), type="conv_end"))

    def close(self):
        self.log.emit({"type": "run_end", "run": self.run_id, "turns": self.turns, "noise_turns": self.noise_turns})
        self.log.close()
        self.adapter.shutdown()

    # ---- scripted cases
    def run_case(self, sc, case):
        cid = case["id"]
        self.start_conv(sc, cid, case.get("kind", "case"), case["user"], expect=case.get("expect") or {},
                        family=case.get("family"), title=case.get("title"), case=case,
                        persona=case.get("persona"))
        try:
            sc.toolbox.clear_faults()
            if case.get("clock"):
                ck = case["clock"]
                sc.world.t = float(ck.get("t", sc.world.t))
                if "hour" in ck or "minute" in ck:  # start this case at a time of day
                    sc.world.set_time(ck.get("hour", sc.world.hour()), ck.get("minute", 0))
                if ck.get("days"):
                    sc.world.advance(days=float(ck["days"]))
            self.patch(sc, cid, case.get("setup"))
            open_, counts = {}, {}
            for step in case["steps"]:
                if "say" in step:
                    key = step["session"]
                    if key not in open_:
                        counts[key] = counts.get(key, 0) + 1
                        sid = f"{cid}:{key}" + (f"#{counts[key]}" if counts[key] > 1 else "")
                        open_[key] = (sid, step.get("user", case["user"]))
                        self.open_session(sc, cid, *open_[key])
                    sid, user = open_[key]
                    extra = {"expect": step["expect"]} if step.get("expect") else {}
                    self.say(sc, cid, sid, user, step["say"], **extra)
                elif "fail" in step:
                    self.fault(sc, cid, step["fail"])
                elif "advance" in step:
                    self.advance(sc, cid, **{k: float(v) for k, v in step["advance"].items()})
                elif "close" in step:
                    if step["close"] in open_:
                        self.close_session(sc, cid, *open_.pop(step["close"]))
                elif "patch" in step:
                    self.patch(sc, cid, step["patch"])
            for sid, user in open_.values():
                self.close_session(sc, cid, sid, user)
        except SpecError as e:
            raise SpecError(f"case {cid}: {e}") from None
        except (TypeError, ValueError) as e:
            raise SpecError(f"case {cid}: bad step ({e})") from None
        sc.toolbox.clear_faults()
        self.end_conv(sc, cid, case["user"])

    def run_cases(self, cases, progress=None):
        groups = {}
        for c in cases:
            groups.setdefault(("g:" + str(c["group"])) if c.get("group") else ("c:" + c["id"]), []).append(c)
        done = 0
        for name, members in groups.items():
            sc = self.new_scope(name)
            for c in members:
                self.run_case(sc, c)
                done += 1
                if progress:
                    progress(done, len(cases))


def execute(project, target=None, cases=None, personas=None, log_path=None, run_id="run", seed=None,
            sim_seed=0, max_turns=None, progress=None):
    """Run cases and/or a fixed population once and check the result."""
    from .population import run_population
    d = Driver(project, target, log_path, run_id, seed)
    try:
        if cases:
            d.run_cases(cases, progress)
        if personas:
            run_population(d, personas, sim_seed=sim_seed, max_turns=max_turns)
    finally:
        d.close()
    ch = Checker(project)
    findings = ch.run(d.log.events)
    convs = [e["conv"] for e in d.log.events if e["type"] == "conv_start"]
    return {"events": d.log.events, "findings": findings, "warnings": ch.warnings, "turns": d.turns,
            "convs": convs, "noise_turns": d.noise_turns}


def noise_stats(events):
    """How often the target answered with a declared noise reply, measured from the log."""
    msgs = sum(1 for e in events if e["type"] == "user_msg")  # every send, resends included
    noise = [e for e in events if e["type"] == "noise"]
    return {"sends": msgs, "noise_replies": len(noise), "rate": round(len(noise) / msgs, 4) if msgs else 0.0,
            "with_tool_calls": sum(1 for e in noise if e.get("calls")),
            "with_data_changes": sum(1 for e in noise if e.get("changes"))}


def transcript(events, conv, tools=True, width=100):
    """Human-readable lines for one conversation. width=None prints tool results in full."""
    lines, sessions = [], []
    many = sum(1 for e in events if e.get("conv") == conv and e["type"] == "session_start") > 1
    for e in events:
        if e.get("conv") != conv:
            continue
        t = e["type"]
        if t == "session_start":
            sessions.append(e["session"])
            lines.append(f"--- conversation window {len(sessions)} (user {e.get('user')}, day {e.get('day')})")
        elif t == "user_msg" and e.get("resend"):
            lines.append("    (that reply is declared noise: the same message was sent again)")
        elif t == "user_msg":
            tag = f"[window {sessions.index(e['session']) + 1}] " if many and e.get("session") in sessions else ""
            lines.append(f"{tag}User: {e['text']}")
        elif t == "bot_msg":
            lines.append(f"System: {e['text']}")
        elif t == "tool_call" and tools:
            if tools == "changes" and not e.get("changes") and not e.get("error"):
                continue  # look-ups are left out; only what the system changed, or failed to do
            args = ", ".join(f"{k}={v}" for k, v in (e.get("args") or {}).items())
            res = f"failed: {e['error']}" if e.get("error") else json.dumps(e.get("result"))[:width]
            lines.append(f"    (the system did: {e['name']}({args}) -> {res})")
        elif t == "target_error":
            lines.append(f"    (system error: {e.get('error')})")
        elif t == "clock":
            adv = ", ".join(f"{v:g} {k}" for k, v in e["advance"].items())
            lines.append(f"--- time passes: {adv}")
        elif t == "fault":
            f = e.get("fault") or {}
            lines.append("--- test setup: backend failures cleared" if f.get("clear") else
                         f"--- test setup: the next {f.get('tool')} call fails ({f.get('error', 'backend unavailable')})")
        elif t == "world_patch":
            lines.append(f"--- test setup changed {len(e.get('changes', []))} value(s) in the sandbox")
    return lines
