"""Replay a failure N times (how often does it really happen?), shrink it to the shortest
script that still shows it, and export that script as a new written case.

Shrinking must never shrink away the cause. How much may be cut depends on what kind of evidence
the failure rests on (see `shrink_mode`):

  full   built-in checks and rules (rule:*, unconfirmed_action, privacy_leak, ...). The check
         carries its own evidence, so any script on which it still fires is a true failure:
         classic delta debugging over messages, set-up and clock.
  trim   "must not happen" expectations (expect:no_calls, expect:unchanged, expect:*_not_*). The
         expectation only means something together with the steps that make the action wrong, and
         no program can tell which message that is (in 1.0 "transfer, no, transfer 200, yes" became
         "transfer, yes"). So every message that says something is kept, with every clock jump,
         outside change, backend failure, window switch and the whole set-up. Cut are only
         (a) everything after the violation, which is provably safe: a forbidden call, change or
         reply that has happened stays happened, so a prefix that still fails holds the whole
         cause; and (b) filler (greetings, thanks, junk) before the first step that matters.
  inert  "did not happen" expectations (expect:calls, expect:world, expect:*_contains, goals).
         Deleting a message can only make the expected thing less likely, and a product whose bug
         is that it ignores a message behaves the same without that message. So only filler is
         cut, and only when every other exchange (replies and tool calls) stays exactly as it was
         and the same expectation still fails.

Filler is what the vocabulary pack lists under say.hello, say.bye and junk ("hi", "thanks",
"sent from my phone"); a project adds its own in vocab.json. A message read as a yes or a no is
never filler.

In every mode the candidate must fail on the SAME expectation entry (expect_key), the result is
replayed before it is shown, and `export_case` refuses to save a script that passes.
"""
import copy
import json
import os
import re

from .runner import execute
from .vocab import Stance, normalise
from .world import SpecError, apply_changes, changes_to_patches, diff


class ExportRefused(SpecError):
    """The script to export does not fail on the expectation / check that defined the failure."""


def world_before(project, events, conv):
    """What had already changed in the sandbox when this conversation began."""
    seed = next((e.get("world_seed") for e in events if e["type"] == "run_start"), project.seed)
    start = next((e for e in events if e["type"] == "conv_start" and e["conv"] == conv), None)
    if start is None:
        raise SpecError(f"no conversation {conv!r} in this run")
    base = project.new_world(seed)
    mirror = project.new_world(seed)
    for e in events:
        if e["seq"] >= start["seq"]:
            break
        if e.get("scope") == start.get("scope") and e["type"] in ("tool_call", "world_patch"):
            apply_changes(mirror.data, e.get("changes") or [])
    return diff(base.data, mirror.data), start


def case_from_log(project, events, conv):
    """Rebuild one conversation as a self-contained case (world state, clock, messages)."""
    pre, start = world_before(project, events, conv)
    if start.get("case"):
        case = copy.deepcopy(start["case"])
        case.pop("group", None)
        case["setup"] = changes_to_patches(pre) + list(case.get("setup") or [])
        if start.get("t"):
            # the clock as it stood when this conversation began; the case's own "clock" (a time of
            # day, for instance) was already applied on top of it in the original run
            own = {k: v for k, v in (case.get("clock") or {}).items() if k != "t"}
            case["clock"] = dict(own, t=start["t"]) if "t" not in (case.get("clock") or {}) else case["clock"]
        return case
    steps, keys, last_t = [], {}, start.get("t", 0)
    for e in events:
        if e.get("conv") != conv:
            continue
        if e["type"] == "session_start":
            keys[e["session"]] = (chr(ord("a") + len(keys)) if len(keys) < 26 else f"s{len(keys)}", e.get("user"))
        elif e["type"] == "user_msg" and not e.get("resend"):
            gap = e.get("t", last_t) - last_t
            if gap >= 720:
                steps.append({"advance": {"days": round(gap / 1440, 2)}})
            last_t = e.get("t", last_t)
            key, user = keys.get(e["session"], ("a", start.get("user")))
            st = {"session": key, "say": e["text"]}
            if user and user != start.get("user"):
                st["user"] = user
            steps.append(st)
    case = {"id": conv, "user": start.get("user"), "steps": steps, "expect": start.get("expect") or {},
            "setup": changes_to_patches(pre), "kind": start.get("kind", "case")}
    if start.get("persona"):
        case["persona"] = {"goal": start["persona"].get("goal")}
    if start.get("t"):
        case["clock"] = {"t": start["t"]}
    return case


def matches(f, code, key=None):
    return f["code"] == code and (key is None or f.get("expect_key") == key)


def fires(project, target, case, code, tries=1, key=None):
    """(hits, result of the last run in which the problem showed). With `key`, only a failure of
    that same expectation entry counts."""
    hits, shown = 0, None
    for _ in range(tries):
        try:
            res = execute(project, target, cases=[case], run_id="replay")
        except SpecError:
            continue
        if any(matches(f, code, key) for f in res["findings"]):
            hits += 1
            shown = res
    return hits, shown


def reproduce(project, target, case, code, n=5, key=None):
    hits, shown = fires(project, target, case, code, n, key)
    return {"hits": hits, "n": n, "rate": hits / n if n else 0.0}, shown


def rerun(project, target, cases, times=2, progress=None):
    """Run a batch of rebuilt conversations again `times` times. Returns {(conv, code, key): hits}
    so that every single finding gets its own reproduction count."""
    hits = {}
    for k in range(max(0, times)):
        try:
            res = execute(project, target, cases=cases, run_id="rerun",
                          progress=(lambda done, total, k=k: progress(k * total + done, times * total)) if progress else None)
        except SpecError:
            continue
        for k in {(f["conv"], f["code"], f.get("expect_key")) for f in res["findings"]}:
            hits[k] = hits.get(k, 0) + 1
    return hits


MUST_NOT = ("no_calls", "unchanged", "reply_not_contains", "reply_not_matches",
            "last_reply_not_contains", "last_reply_not_matches")
MONOTONE = ("no_calls", "unchanged", "reply_not_contains", "reply_not_matches")  # once true, stays true


def expect_kind(code, key=None):
    """The expectation kind behind a finding ("no_calls", "calls", ...), or None for other checks."""
    if key:
        k = key.rsplit(".", 1)[-1] if key.startswith("step<") else key
        return k.split("[", 1)[0]
    if code.startswith("expect:"):
        k = code.split(":", 1)[1]
        return k[5:] if k.startswith("step_") else k
    return None


def shrink_mode(code, key=None):
    """'full', 'trim' or 'inert': how freely a failure of this kind may be shrunk (module docstring)."""
    if not code.startswith(("expect:", "goal_not_met")):
        return "full"
    kind = expect_kind(code, key)
    if kind in MUST_NOT:
        return "trim"
    return "inert"


def shrinkable(code, key=None):
    """Kept for callers of 1.0: every kind of failure can now be shrunk, each in its own mode."""
    return True


def ddmin(items, test, budget):
    """Classic delta debugging: drop chunks while `test` still passes (= still fails the target)."""
    cur, n = list(items), 2
    while len(cur) >= 2 and budget[0] > 0:
        chunk = max(1, len(cur) // n)
        parts = [cur[i:i + chunk] for i in range(0, len(cur), chunk)]
        reduced = False
        for k in range(len(parts)):
            cand = [x for j, p in enumerate(parts) if j != k for x in p]
            if budget[0] <= 0:
                break
            budget[0] -= 1
            if test(cand):
                cur, n, reduced = cand, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(cur):
                break
            n = min(len(cur), n * 2)
    if len(cur) == 1 and budget[0] > 0:
        budget[0] -= 1
        if test([]):
            cur = []
    return cur


def _entry_values(case, key):
    """Literal values named by the failing expectation entry (ids, argument values, expected text)."""
    out = []
    if not key or key.startswith("step<"):
        return out
    kind, _, idx = key.partition("[")
    try:
        entry = (case.get("expect") or {}).get(kind, [])[int(idx.rstrip("]"))]
    except (ValueError, IndexError, TypeError):
        return out

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k not in ("tool", "entity", "field", "count", "ok", "expr", "exists"):
                    walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif v is not None and not isinstance(v, bool) and len(str(v)) >= 2:
            out.append(str(v).lower())
    walk(entry)
    return out


def filler_messages(project):
    """Messages that carry no request: greetings, thanks and junk from the vocabulary pack."""
    v = project.vocab
    out = set()
    for act in ("hello", "bye"):
        for lines in (v.get("say", {}).get(act) or {}).values():
            out.update(normalise(x) for x in lines)
    out.update(normalise(x) for x in v.get("junk", []))
    out.discard("")
    return out


def protected_steps(project, case, mode, key=None):
    """Indexes of steps a shrink in this mode must keep, with the reason for each. In the two
    expectation modes that is everything except filler in the first window."""
    stance = Stance(project.vocab)
    filler = filler_messages(project)
    keep, first_session = {}, None
    values = _entry_values(case, key)
    for i, s in enumerate(case["steps"]):
        if "say" not in s:
            keep[i] = "a clock jump, outside change, backend failure or closed window"
            continue
        sess = s.get("session", "main")
        if first_session is None:
            first_session = sess
        st = stance(s["say"])
        low = s["say"].lower()
        if st == "no":
            keep[i] = "the user says no here"
        elif st == "yes":
            keep[i] = "the user says yes here"
        elif sess != first_session or (s.get("user") and s["user"] != case.get("user")):
            keep[i] = "another window or another user"
        elif s.get("expect"):
            keep[i] = "this step has its own expectation"
        elif any(v in low for v in values):
            keep[i] = "it names a value the expectation is about"
        elif normalise(s["say"]) not in filler:
            keep[i] = "it says something (not a greeting, thanks or junk)"
    return keep


def exchanges(events, conv):
    """What happened after each user message: [(session, text, (replies), (calls))]."""
    out, cur = [], None
    for e in events:
        if e.get("conv") != conv:
            continue
        t = e["type"]
        if t == "user_msg" and not e.get("resend"):
            cur = [e.get("session"), e["text"], [], []]
            out.append(cur)
        elif cur is None:
            continue
        elif t == "bot_msg" and not e.get("noise"):
            cur[2].append(e["text"])
        elif t == "tool_call":
            cur[3].append((e["name"], json.dumps(e.get("args"), sort_keys=True, default=str), bool(e.get("error")),
                           json.dumps(e.get("changes"), sort_keys=True, default=str)))
        elif t == "target_error":
            cur[2].append("<error>")
    return [(a, b, tuple(c), tuple(d)) for a, b, c, d in out]


def shrink(project, target, case, code, tries=2, max_checks=120, key=None, info=None):
    """Shortest script that still shows the problem at least once in `tries` replays (the target
    may be non-deterministic), cut only as far as the failure's kind allows. Returns
    (case, checks_used); `info` (a dict, optional) receives the mode and what was kept and why."""
    budget = [max_checks]
    cur = copy.deepcopy(case)
    mode = shrink_mode(code, key)
    info = info if info is not None else {}
    info.update(mode=mode, kept={})

    def with_(key_, items):
        c = dict(cur)
        c[key_] = items
        return c

    def run_steps(items):
        if not any("say" in s for s in items):
            return 0, None
        budget[0] -= 1
        return fires(project, target, with_("steps", items), code, tries, key)

    if mode == "full":
        def test_steps(items):
            return run_steps(items)[0] > 0

        cur["steps"] = ddmin(cur["steps"], lambda items: any("say" in s for s in items) and
                             fires(project, target, with_("steps", items), code, tries, key)[0] > 0, budget)
        # drop "close"/"advance" steps one by one if they are not needed
        for s in [s for s in cur["steps"] if "say" not in s]:
            if budget[0] <= 0:
                break
            cand = [x for x in cur["steps"] if x is not s]
            if test_steps(cand):
                cur["steps"] = cand
        if cur.get("setup"):
            cur["setup"] = ddmin(cur["setup"],
                                 lambda items: fires(project, target, with_("setup", items), code, tries, key)[0] > 0,
                                 budget)
            if not cur["setup"]:
                cur.pop("setup")
        if cur.get("clock") and budget[0] > 0:
            cand = {k: v for k, v in cur.items() if k != "clock"}
            if fires(project, target, cand, code, tries, key)[0] > 0:
                cur = cand
        return cur, max_checks - budget[0]

    kind = expect_kind(code, key)
    if mode == "trim":
        # 1. everything after the violation: once a forbidden call / change / reply has happened it
        #    stays happened, so a shorter prefix that still fails contains the whole cause.
        if kind in MONOTONE:
            while len(cur["steps"]) > 1 and budget[0] > 0:
                if run_steps(cur["steps"][:-1])[0] > 0:
                    cur["steps"] = cur["steps"][:-1]
                else:
                    break
        # 2. filler before the first step that must be kept, from the front, stopping at the first
        #    one that turns out to be needed.
        while budget[0] > 0:
            keep = protected_steps(project, cur, mode, key)
            if not cur["steps"] or 0 in keep or len(cur["steps"]) < 2:
                break
            if run_steps(cur["steps"][1:])[0] > 0:
                cur["steps"] = cur["steps"][1:]
            else:
                break
    else:
        # inert: cut filler only, and only if nothing else in the conversation notices.
        hits, shown = fires(project, target, cur, code, 1, key)
        budget[0] -= 1
        base = exchanges(shown["events"], cur["id"]) if shown else None
        i = len(cur["steps"]) - 1
        while base is not None and i >= 0 and budget[0] > 0:
            keep = protected_steps(project, cur, mode, key)
            if i in keep or "say" not in cur["steps"][i]:
                i -= 1
                continue
            cand = cur["steps"][:i] + cur["steps"][i + 1:]
            n_say = sum(1 for s in cur["steps"][:i] if "say" in s)
            h, res = run_steps(cand)
            if h > 0 and exchanges(res["events"], cur["id"]) == base[:n_say] + base[n_say + 1:]:
                cur["steps"] = cand
                base = base[:n_say] + base[n_say + 1:]
            i -= 1
    info["kept"] = {str(i): why for i, why in protected_steps(project, cur, mode, key).items()}
    return cur, max_checks - budget[0]


def validated_shrink(project, target, case, code, key=None, tries=3, max_checks=120):
    """Shrink, then replay the result: a shrunk script is only returned if it still fails on the
    check / expectation entry that defined the failure. Returns (case, info); info has mode,
    checks, validated (bool), shown (the run in which the short script failed) and kept."""
    info = {}
    short, checks = shrink(project, target, case, code, max_checks=max_checks, key=key, info=info)
    hits, shown = fires(project, target, short, code, tries, key)
    info.update(checks=checks, validated=hits > 0, shown=shown, replay_hits=hits, replay_n=tries)
    if hits == 0:
        short = case
        info["fell_back"] = True
    return short, info


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:60]


def export_form(case, code, detail="", key=None):
    """The regression case that would be saved, and the (code, key) on which it must fail."""
    out = {k: v for k, v in case.items() if k not in ("kind", "persona")}
    out["id"] = f"regress-{slug(case['id'])}-{slug(code)}"
    out["family"] = "regression"
    out["title"] = f"Shrunk from a failure: {code}"
    out["origin"] = {"code": code, "detail": detail, "from": case["id"]}
    # The saved case must fail only while THIS problem exists: built-in checks and rules fire on
    # their own, so the original expectations (written for the unshrunk script) are dropped, and of
    # a failed expectation only the one entry that failed is kept.
    orig = case.get("expect") or {}
    out["expect"] = {}
    want_code, want_key = code, None
    kind = expect_kind(code, key)
    if code.startswith(("expect:", "goal_not_met")) and not (key or "").startswith("step<"):
        entries = orig.get(kind)
        if entries:
            idx = None
            if key and "[" in key:
                try:
                    idx = int(key.split("[", 1)[1].rstrip("]"))
                except ValueError:
                    idx = None
            if idx is not None and idx < len(entries):
                out["expect"] = {kind: [entries[idx]]}
                want_key = f"{kind}[0]"
            else:
                out["expect"] = {kind: entries}
            want_code = f"expect:{kind}"
    elif (key or "").startswith("step<"):
        want_key = key  # the expectation lives on the step itself
    return out, want_code, want_key


def export_case(project, case, code, detail="", directory=None, key=None, target=None, validate=True, tries=3):
    """Write a (shrunk) failure as a regression case; returns the path. The case is replayed first:
    if it passes on the expectation or check that defined the failure, nothing is written and
    ExportRefused is raised, because a regression case that does not fail now proves nothing later
    (and one that fails for a different reason would fail forever on a correct product)."""
    from .project import normalise_case
    directory = directory or os.path.join(project.path(project.config.get("cases", "cases")), "regressions")
    out, want_code, want_key = export_form(case, code, detail, key)
    if validate:
        hits, _ = fires(project, target, normalise_case(copy.deepcopy(out)), want_code, tries, want_key)
        if hits == 0:
            what = f"expectation {want_key}" if want_key else want_code
            raise ExportRefused(f"not exported: replayed {tries} time(s), this script passes on the {what} that "
                                f"defined the failure ({code}). Export the original conversation instead, or "
                                f"check whether the failure depends on what earlier conversations left behind.")
        out["origin"]["validated"] = f"failed {hits} of {tries} replays before it was saved"
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, out["id"] + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    return path
