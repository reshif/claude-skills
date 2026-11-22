"""poptest: test software that takes actions over time, against a fake world you control.

  poptest init [DIR] [--example NAME]   start a project (world, tools, rules, cases, config)
  poptest validate                      check every project file and summarise case coverage
  poptest world [--entity E ...]        look at the generated sandbox data (ids for writing cases)
  poptest say --user U "msg" ...        send a few messages by hand and see what the system did
  poptest run                           run cases (and --population), check, replay, shrink, report
  poptest show RUN CONVERSATION         print one conversation from a run
  poptest replay RUN CONVERSATION       replay one failure N times; --shrink; --export
  poptest compare --a A --b B           compare two releases with a pre-declared rule
  poptest mutate                        plant faults in the target; measure what the tests catch
  poptest personas                      preview the simulated users
  poptest serve-tools                   run the fake-tools HTTP server for wiring up a target
"""
import argparse
import json
import os
import shutil
import sys
import time

from . import compare as compare_mod
from . import mutate as mutate_mod
import re

from . import population, replay, report
from .checks import EXPECT_KEYS, STEP_EXPECT, Checker
from .project import FAMILIES, Project, normalise_case
from .runner import Driver, Noise, execute, noise_stats, read_log, transcript
from .tools import ToolBox, ToolServer
from .world import VERSION, SpecError, safe_eval

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def out(*a):
    print(*a)


def _write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _next_run(project, name=None):
    base = os.path.join(project.root, "runs")
    os.makedirs(base, exist_ok=True)
    if not name:
        n = 1
        while os.path.exists(os.path.join(base, f"run-{n:03d}")):
            n += 1
        name = f"run-{n:03d}"
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    _write(os.path.join(base, "latest"), name + "\n")
    return name, d


def _run_dir(project, name):
    base = os.path.join(project.root, "runs")
    if name in (None, "latest"):
        try:
            with open(os.path.join(base, "latest")) as f:
                name = f.read().strip()
        except FileNotFoundError:
            raise SpecError("no runs yet: use 'poptest run' first") from None
    d = name if os.path.isdir(name) else os.path.join(base, name)
    if not os.path.exists(os.path.join(d, "events.jsonl")):
        raise SpecError(f"no run {name!r} (looked for {d}/events.jsonl)")
    return d


def _personas(project, a, target=None):
    if getattr(a, "personas_file", None):
        with open(a.personas_file) as f:
            return json.load(f), {}
    people, info = population.guided_population(project, target, budget=a.budget, seed=a.sim_seed)
    info["personas"] = len(people)
    return people, info


# ---------------------------------------------------------------------------- commands
SAMPLE_NOTE = {
    "target/": "the sample system under test (a task list). Delete it once your own target is connected.",
    "world.json": "sample world: users and tasks. Replace with your own entities.",
    "tools.json": "sample fake tools for the task list. Replace together with tools.py.",
    "tools.py": "sample tool handlers.",
    "rules.json": "sample rules; its 'actions' name the sample tools, so replace them with your tools.",
    "cases/": "five sample cases (cases/starter.json) for the task list. Delete them.",
    "population.json": "sample simulated-user goals for the 'tasks' entity. Rewrite or delete (optional file).",
    "vocab.json": "empty: add product-specific ways of saying yes and no here.",
    "poptest.json": "the project config: point 'target' at your system.",
}
BARE = {
    "poptest.json": {"name": "my-project", "seed": 7, "target": {}, "world": "world.json", "tools": "tools.json",
                     "rules": "rules.json", "cases": "cases", "vocab": "vocab.json",
                     "compare": {"rule": {"reps": 3, "min_b": 2, "max_a": 0}}},
    "world.json": {"clock": {"start_day": 1000, "start_date": "2026-01-05", "start_hour": 9},
                   "user_entity": "users", "entities": {"users": {"records": [{"id": "user1", "name": "First user"}]}}},
    "tools.json": {"module": "tools.py", "tools": {}},
    "rules.json": {"actions": {}, "facts": [], "invariants": []},
    "vocab.json": {"affirm": [], "negate": [], "say": {}},
}


def cmd_init(a):
    dest = os.path.abspath(a.dir)
    if os.path.exists(os.path.join(dest, "poptest.json")) and not a.force:
        raise SpecError(f"{dest} already has a poptest.json (use --force to overwrite files)")
    if a.bare:
        if a.example:
            raise SpecError("use either --bare or --example, not both")
        os.makedirs(os.path.join(dest, "cases"), exist_ok=True)
        for name, obj in BARE.items():
            _write(os.path.join(dest, name), json.dumps(obj, indent=1) + "\n")
        _write(os.path.join(dest, "tools.py"), '"""Fake tools: one function per tool in tools.json, first parameter `world`."""\n'
                                                "from poptest.tools import ToolError  # noqa: F401  raise ToolError(msg, status=404)\n")
        out(f"Created an empty poptest project in {dest} (no sample target, world, tools, rules or cases).")
        out("\nNext: fill in 'target' in poptest.json (connect-target skill), then world.json, tools.json + tools.py "
            "(build-world), rules.json (write-rules) and cases/ (generate-cases).\n"
            "  poptest validate --no-target      # passes on this skeleton; run it after every file you write")
        return 0
    src = os.path.join(PLUGIN_ROOT, "examples", a.example) if a.example else os.path.join(PLUGIN_ROOT, "templates", "project")
    if not os.path.isdir(src):
        names = sorted(os.listdir(os.path.join(PLUGIN_ROOT, "examples")))
        raise SpecError(f"no example {a.example!r}. Available: {', '.join(names)}")
    shutil.copytree(src, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "runs", "*.pyc"))
    out(f"Created a poptest project in {dest}")
    for f in sorted(os.listdir(dest)):
        name = f + ("/" if os.path.isdir(os.path.join(dest, f)) else "")
        note = SAMPLE_NOTE.get(name) if not a.example else None
        out("  " + name + (f"   <- {note}" if note else ""))
    out("\nNext:\n  cd " + a.dir + "\n  poptest validate\n  poptest run")
    if not a.example:
        out("Everything above is a small runnable SAMPLE (a task list), so that validate and run work at once. "
            "The sample files refer to each other: when you replace world.json, also replace or delete "
            "rules.json 'actions', population.json and cases/starter.json, or validate will tell you which "
            "of them still names a sample tool or entity. To start from empty files instead: "
            "poptest init DIR --bare.\n"
            "The skills connect-target, build-world, write-rules and generate-cases walk through it.")
    return 0


def _guard(problems, what, fn):
    """Run one part of validation; whatever goes wrong inside becomes a clear PROBLEM line."""
    try:
        return fn()
    except SpecError as e:
        problems.append(f"{what}: {e}")
    except Exception as e:  # a project file with an unexpected shape: say where, never a traceback
        problems.append(f"{what}: could not be checked ({type(e).__name__}: {e}). The file probably has "
                        f"a different shape from the one the skills describe.")
    return None


def cmd_validate(a):
    try:
        p = Project(a.project)
    except SpecError:
        raise
    except Exception as e:
        raise SpecError(f"a project file could not be read ({type(e).__name__}: {e}). Check poptest.json, world.json, "
                        f"tools.json and rules.json against the shapes in the build-world and write-rules skills.") from None
    problems, notes = [], []
    try:
        w = p.new_world()
    except SpecError:
        raise
    except Exception as e:
        raise SpecError(f"world.json: the sandbox could not be built ({type(e).__name__}: {e}). Check the "
                        f"'generate' blocks and 'records' against the build-world skill.") from None
    out(f"Project: {p.name}  ({p.root})")
    out(f"World (seed {p.seed}): " + ", ".join(f"{len(v)} {k}" for k, v in w.data.items())
        + f"; the clock starts on day {w.day} ({w.date()}) at {w.time()}")
    ents = p.world_spec["entities"]
    tools = p.tools_spec.get("tools", {})
    rules = p.rules or {}
    acts = rules.get("actions", {})

    def check_world():
        for ent, es in ents.items():
            fields = set()
            for rec in w.data[ent].values():
                fields.update(rec)
            for key in ("private_fields", "detail_fields"):
                for f in es.get(key, []):
                    if w.data[ent] and f not in fields:
                        problems.append(f"world: {ent}.{key} names '{f}', which no record has")
            if es.get("owner_field") and w.data[ent] and es["owner_field"] not in fields:
                problems.append(f"world: {ent}.owner_field '{es['owner_field']}' is not a field of its records")
            for rec in w.data[ent].values():
                o = rec.get(es.get("owner_field")) if es.get("owner_field") else None
                if o is not None and w.get(w.user_entity, o) is None:
                    problems.append(f"world: {ent} {rec.get(es.get('id_field', 'id'))} is owned by unknown user {o!r}")
                    break
            for key in ("shared_with",):
                if key in es:
                    try:
                        compile(es[key], "<rule>", "eval")
                    except (SyntaxError, TypeError) as e:
                        problems.append(f"world: {ent}.{key} is not a valid expression: {getattr(e, 'msg', e)}")
        if not any(es.get("private_fields") for es in ents.values()):
            notes.append("no entity declares private_fields: the privacy check has nothing to look for")

    def check_tools():
        out(f"Tools: {len(tools)} ({', '.join(tools)})")
        for name, t in tools.items():
            for arg, spec in (t.get("args") or {}).items():
                if isinstance(spec, dict) and spec.get("ref") and spec["ref"] not in ents:
                    problems.append(f"tools: {name}.{arg} refers to unknown entity {spec['ref']!r}")
            for e in t.get("writes") or []:
                if e not in ents:
                    problems.append(f"tools: {name}.writes names unknown entity {e!r}")

    def check_rules():
        out(f"Rules: {len(acts)} action(s) needing care, {len(rules.get('facts', []))} fact check(s), "
            f"{len(rules.get('invariants', []))} invariant(s)" + (", plus rules.py" if p.rules_module else ""))
        covered = {act.get("tool", key) for key, act in acts.items()}
        for n, t in tools.items():
            if t.get("mutates", True) and n not in covered:
                notes.append(f"tool '{n}' changes data but has no entry under rules.json 'actions' "
                             f"(no confirmation or false-claim check for it)")
        ch = Checker(p)
        for key, act in acts.items():
            ch.question_patterns(key, act)   # raises a clear error for a bad pattern
            for pat in act.get("claims", []):
                try:
                    re.compile(pat)
                except re.error as e:
                    problems.append(f"rules: actions.{key}.claims pattern {pat!r}: {e}")
            for item in act.get("must_mention", []):
                names = [item] if isinstance(item, str) else [item["arg"]] if "arg" in item else list(item)
                declared = tools.get(act.get("tool", key), {}).get("args") or {}
                for nm in names:
                    if declared and str(nm).split(".")[0] not in declared:
                        problems.append(f"rules: actions.{key}.must_mention names '{nm}', which is not an argument "
                                        f"of {act.get('tool', key)}")
            unknown = set(act) - {"tool", "when", "label", "needs_confirmation", "question_keywords", "question_patterns",
                                  "must_mention", "claims", "claim_scope", "cross_user"}
            if unknown:
                problems.append(f"rules: actions.{key} has unknown key(s) {sorted(unknown)}")
        conf = rules.get("confirmation")
        if conf is not None and (not isinstance(conf, dict) or set(conf) - {"question_patterns"}):
            problems.append("rules: 'confirmation' takes one key: {\"question_patterns\": [\"regex\", ...]}")
        ids = set()
        for r in rules.get("invariants", []):
            if not isinstance(r, dict) or not r.get("id") or r.get("on") not in ("call", "tool_call", "change", "reply", "end"):
                rid = r.get("id", r) if isinstance(r, dict) else r
                problems.append(f"rules: invariant {rid!r} needs an id and on = call | change | reply | end")
                continue
            if r["id"] in ids:
                problems.append(f"rules: duplicate invariant id {r['id']}")
            ids.add(r["id"])
            for key in ("when", "require"):
                if key in r:
                    try:
                        compile(r[key], "<rule>", "eval")
                    except (SyntaxError, TypeError) as e:
                        problems.append(f"rules: {r['id']}.{key} is not a valid expression: {getattr(e, 'msg', e)}")
            if "require" not in r:
                problems.append(f"rules: {r['id']} has no 'require'")
            if r.get("match"):
                try:
                    re.compile(r["match"])
                except re.error as e:
                    problems.append(f"rules: {r['id']}.match is not a valid pattern: {e}")
            t = r.get("tool")
            for name in ([t] if isinstance(t, str) else t or []):
                if name not in tools:
                    problems.append(f"rules: {r['id']} names unknown tool {name!r}")
            if r.get("entity") and r["entity"] not in ents:
                problems.append(f"rules: {r['id']} names unknown entity {r['entity']!r}")
        for fct in rules.get("facts", []):
            if "phrases" not in fct and not ("pattern" in fct and "truth" in fct):
                problems.append(f"rules: fact {fct.get('id')!r} needs 'phrases' or 'pattern' + 'truth'")
            if "pattern" in fct:
                try:
                    re.compile(fct["pattern"])
                except re.error as e:
                    problems.append(f"rules: fact {fct.get('id')!r} pattern: {e}")
            if fct.get("entity") and fct["entity"] not in ents:
                problems.append(f"rules: fact {fct.get('id')!r} names unknown entity {fct['entity']!r}")

    def check_cases():
        try:
            cases = p.load_cases(a.cases or None)
        except SpecError as e:
            cases = []
            problems.append(str(e))
        fam = {}
        multi_session = concurrent = clock = 0
        allowed = set(p.config.get("unknown_users") or [])
        for c in cases:
            fam[c.get("family") or "unlabelled"] = fam.get(c.get("family") or "unlabelled", 0) + 1
            added = {str(x["add"].get(w.id_field(x["entity"]))) for x in c.get("setup") or []
                     if isinstance(x, dict) and isinstance(x.get("add"), dict) and x.get("entity") in ents}
            users = {c["user"]} | {s["user"] for s in c["steps"] if s.get("user")}
            ok_unknown = allowed | ({str(u) for u in users} if c.get("unknown_user") is True else
                                    set(c.get("unknown_user") or []) if isinstance(c.get("unknown_user"), list) else
                                    {str(c["unknown_user"])} if c.get("unknown_user") else set())
            for u in sorted(users, key=str):
                if w.get(w.user_entity, u) is None and u not in added and str(u) not in ok_unknown:
                    problems.append(f"case {c['id']}: unknown user {u!r}. If the case is about a user the backend "
                                    f"does not know, say so with \"unknown_user\": true in the case (or list the id "
                                    f"under \"unknown_users\" in poptest.json).")
            for key in ("setup",):
                for x in c.get(key) or []:
                    if not isinstance(x, dict) or x.get("entity") not in ents or not ({"set", "add", "delete"} & set(x)):
                        problems.append(f"case {c['id']}: every setup patch needs a known 'entity' and one of "
                                        f"set / add / delete (got {json.dumps(x)[:80]})")
            exp = c.get("expect") or {}
            if not isinstance(exp, dict):
                problems.append(f"case {c['id']}: 'expect' must be an object")
                exp = {}
            for key in exp:
                if key not in EXPECT_KEYS:
                    problems.append(f"case {c['id']}: unknown expectation '{key}'. Known: {', '.join(EXPECT_KEYS)}")
                elif not isinstance(exp[key], list):
                    problems.append(f"case {c['id']}: expect.{key} must be a list")
            for key in ("calls", "no_calls"):
                for e in exp.get(key, []) if isinstance(exp.get(key, []), list) else []:
                    t = e if isinstance(e, str) else e.get("tool")
                    if t not in tools:
                        problems.append(f"case {c['id']}: expect.{key} names unknown tool {t!r}")
            for key in ("world", "unchanged"):
                for e in exp.get(key, []) if isinstance(exp.get(key, []), list) else []:
                    ent = e if isinstance(e, str) and key == "unchanged" else e.get("entity") if isinstance(e, dict) else None
                    if ent is not None and ent not in ents:
                        problems.append(f"case {c['id']}: expect.{key} names unknown entity {ent!r}")
            seen, closed, inter, owner = [], set(), False, {}
            for i, s in enumerate(c["steps"]):
                if "say" in s:
                    u = s.get("user", None)
                    if s["session"] not in owner or s["session"] in closed:
                        owner[s["session"]] = u or c["user"]
                    elif u and u != owner[s["session"]]:
                        problems.append(f"case {c['id']} step {i + 1}: session '{s['session']}' already belongs to "
                                        f"{owner[s['session']]}; a later step cannot switch it to {u}. Give the "
                                        f"other user their own session name.")
                    for key in (s.get("expect") or {}):
                        if key not in STEP_EXPECT:
                            problems.append(f"case {c['id']} step {i + 1}: unknown step expectation '{key}'. "
                                            f"Known: {', '.join(STEP_EXPECT)}")
                    if s["session"] not in seen:
                        seen.append(s["session"])
                    elif len(seen) > 1 and s["session"] != seen[-1] and s["session"] not in closed:
                        inter = True
                    closed.discard(s["session"])
                elif "close" in s:
                    closed.add(s["close"])
                elif "advance" in s:
                    clock += 1
                elif "fail" in s:
                    t = (s["fail"] or {}).get("tool") if isinstance(s["fail"], dict) else None
                    if not isinstance(s["fail"], dict) or (not s["fail"].get("clear") and t != "*" and t not in tools):
                        problems.append(f"case {c['id']} step {i + 1}: 'fail' needs {{\"tool\": <a tool or \"*\">, "
                                        f"\"error\": text}} or {{\"clear\": true}}")
            still_open = [k for k in seen if k not in closed]
            multi_session += len(seen) > 1
            concurrent += inter or len(still_open) > 1
        out(f"Cases: {len(cases)}  (more than one conversation window: {multi_session}; two windows open at once: "
            f"{concurrent}; with a clock jump: {clock})")
        if cases:
            for f in FAMILIES:
                out(f"  {f:22s} {fam.get(f, 0)}")
            for f, n in sorted(fam.items()):
                if f not in FAMILIES:
                    out(f"  {f:22s} {n}")
            missing = [f for f in FAMILIES if not fam.get(f)]
            if missing:
                notes.append("no cases yet for these failure families: " + ", ".join(missing))

    def check_population():
        if p.population is None:
            return
        if not p.population.get("goals"):
            notes.append("population.json has no goals: population mode (optional) is not set up")
            return
        bad = population.check_spec(p)
        if bad:
            problems.extend(f"population.json: {b}" for b in bad)
            return
        people = population.sample(p, seed=0)
        out(f"Simulated users: {len(people)} in the first round, goals: {', '.join(p.population['goals'])}")
        for g, why in population.unbuildable_goals(p).items():
            notes.append(f"population.json goal '{g}': no simulated user can be built ({why})")

    def check_config():
        noise = Noise(p.config, p.config.get("target") or {})
        if noise:
            out(f"Noise replies: {len(noise.patterns)} pattern(s); a matching reply is recorded and the message "
                f"sent again up to {noise.max_resends} time(s)")
        fl = p.config.get("flake")
        if fl is not None and (not isinstance(fl, dict) or set(fl) - set(report.FLAKE_DEFAULT)):
            problems.append(f"poptest.json 'flake' takes {', '.join(report.FLAKE_DEFAULT)}")
        known = {"name", "seed", "target", "world", "tools", "rules", "cases", "vocab", "population", "compare",
                 "noise", "flake", "unknown_users", "mutate"}
        extra = sorted(k for k in p.config if k not in known and not k.startswith("_"))
        if extra:
            notes.append(f"poptest.json has key(s) poptest does not use: {', '.join(extra)}")

    for what, fn in (("world.json", check_world), ("tools.json", check_tools), ("rules.json", check_rules),
                     ("cases", check_cases), ("population.json", check_population), ("poptest.json", check_config)):
        _guard(problems, what, fn)
    if not a.no_target:
        try:
            d = Driver(p, a.target)
            try:
                d.new_scope("validate")
            finally:
                d.close()
            out(f"Target: starts ({d.cfg.get('adapter', 'python')})")
        except SpecError as e:
            problems.append(f"target: {e}")
        except Exception as e:
            problems.append(f"target could not be started: {type(e).__name__}: {e}")
    for n in notes:
        out("note: " + n)
    for pr in problems:
        out("PROBLEM: " + pr)
    out("OK" if not problems else f"{len(problems)} problem(s) to fix")
    return 1 if problems else 0


def cmd_world(a):
    p = Project(a.project)
    w = p.new_world()
    if a.user:
        res = {w.user_entity: w.get(w.user_entity, a.user)}
        for ent in w.data:
            if ent != w.user_entity:
                res[ent] = [r for r in w.data[ent].values() if w.owner_of(ent, r) == a.user]
        out(json.dumps(res, indent=1))
        return 0
    if a.entity:
        recs = list(w.data[a.entity].values()) if a.entity in w.data else None
        if recs is None:
            raise SpecError(f"unknown entity {a.entity!r}; have: {', '.join(w.data)}")
        if a.where:
            recs = [r for r in recs if safe_eval(a.where, {"rec": r, "world": w, "day": w.day})]
        total = len(recs)
        recs = recs[:a.limit]
        if a.json:
            out(json.dumps(recs, indent=1))
        else:
            for r in recs:
                out(json.dumps(r))
            out(f"({len(recs)} of {total} shown; today is day {w.day}, {w.date()})")
        return 0
    out(f"today is day {w.day} ({w.date()}); users are '{w.user_entity}'")
    for ent, table in w.data.items():
        es = p.world_spec["entities"][ent]
        out(f"\n{ent}: {len(table)} records" + (f", owned via '{es['owner_field']}'" if es.get("owner_field") else "")
            + (f", private: {es['private_fields']}" if es.get("private_fields") else "")
            + (f", details: {es['detail_fields']}" if es.get("detail_fields") else ""))
        for r in list(table.values())[:a.limit if a.limit != 20 else 3]:
            out("  " + json.dumps(r))
    return 0


_JUMP = re.compile(r"^\+(\d+(?:\.\d+)?)\s*(d|days?|h|hours?|m|min|minutes?)$", re.I)


def cmd_say(a):
    """Messages are sent in order in one window. A message of the form +2d, +13h or +30m is not
    sent: it moves the sandbox clock by that much at that point in the conversation."""
    p = Project(a.project)
    steps = []
    for m in a.messages:
        j = _JUMP.match(m.strip())
        if j:
            unit = {"d": "days", "h": "hours", "m": "minutes"}[j.group(2)[0].lower()]
            steps.append({"advance": {unit: float(j.group(1))}})
        else:
            steps.append({"session": "main", "say": m})
    if not any("say" in st for st in steps):
        raise SpecError("say needs at least one message besides clock jumps")
    case = {"id": "adhoc", "user": a.user, "steps": steps}
    if a.days_later:
        case["steps"].insert(0, {"advance": {"days": a.days_later}})
    if a.hour is not None:
        case["clock"] = {"hour": a.hour}
    res = execute(p, a.target, cases=[normalise_case(case)], run_id="say")
    out("\n".join(transcript(res["events"], "adhoc", width=None if a.full else 100)))
    out("")
    if res["findings"]:
        for f in res["findings"]:
            out(f"PROBLEM {f['code']}: {f['detail']}")
    else:
        out("No check fired.")
    for wmsg in res["warnings"]:
        out("warning: " + wmsg)
    return 0


def _progress(label, every=5.0):
    """A progress line on stderr every few seconds, so a long run is never silent."""
    state = {"t": time.time()}

    def tick(done, total):
        now = time.time()
        if now - state["t"] >= every or done == total:
            state["t"] = now
            print(f"  ... {label}: {done} of {total}", file=sys.stderr, flush=True)
    return tick


def cmd_run(a):
    p = Project(a.project)
    cases = [] if a.population_only else p.load_cases(a.cases or None, a.only)
    info, personas = {}, None
    if a.population or a.population_only:
        personas, pinfo = _personas(p, a, a.target)
        info["population"] = pinfo
    if not cases and not personas:
        raise SpecError("nothing to run: no cases found (and --population not given)")
    run_id, d = _next_run(p, a.name)
    t0 = time.time()
    res = execute(p, a.target, cases=cases, personas=personas, log_path=os.path.join(d, "events.jsonl"),
                  run_id=run_id, sim_seed=a.sim_seed, progress=_progress("conversations run"))
    nz = noise_stats(res["events"])
    out(f"{len(res['convs'])} conversations, {res['turns']} user messages, {len(res['findings'])} finding(s) "
        f"in {time.time() - t0:.1f}s."
        + (f" {nz['noise_replies']} noise repl{'y' if nz['noise_replies'] == 1 else 'ies'} ({nz['rate']:.1%} of sends) "
           f"were sent again." if nz["noise_replies"] else ""))
    if res["findings"] and a.replays > 0:
        out("Grouping by root cause, re-running the failing conversations, replaying and shrinking "
            "(skip with --replays 0; faster with --no-shrink or --reruns 0)...")

    def show(pr):
        r = pr.get("replay")
        rr = pr.get("rerun")
        also = [c for c in pr.get("codes", {}) if c != pr["code"]]
        out(f"  [{pr['code']}] {pr['title']}: {pr['count']} conversation(s)"
            + (f", after {pr['trigger_text']}" if pr.get("trigger") else "")
            + (f", replay {r['hits']}/{r['n']}" if r else "")
            + (f", {rr['came_back']} of {rr['came_back'] + rr['did_not']} came back on re-run" if rr and rr["did_not"] else "")
            + ("  [DID NOT REPRODUCE]" if pr.get("flaky") else "")
            + (f"  (also seen as {', '.join(also[:4])}{'...' if len(also) > 4 else ''})" if also else ""))
        sys.stdout.flush()

    problems = report.triage(p, a.target, res["events"], res["findings"], replays=a.replays,
                             do_shrink=not a.no_shrink, export=a.export, progress=show, reruns=a.reruns,
                             rerun_progress=_progress("failing conversations run again"))
    rep = report.build(p, run_id, res["events"], res["findings"], res["warnings"], problems, info)
    _write(os.path.join(d, "report.json"), json.dumps(rep, indent=1, default=str))
    _write(os.path.join(d, "report.md"), report.markdown(rep))
    if personas:
        _write(os.path.join(d, "personas.json"), json.dumps(personas, indent=1, default=str))
    if problems:
        firm = [x for x in problems if not x.get("flaky") and not x["code"].startswith("goal_not_met")]
        out(f"{len(res['findings'])} finding(s) -> {len(firm)} problem(s) by root cause"
            + (f", {sum(1 for x in problems if x.get('flaky'))} group(s) did not reproduce" if any(x.get("flaky") for x in problems) else ""))
    for wmsg in res["warnings"]:
        out("warning: " + wmsg)
    out(f"Report: {os.path.join(d, 'report.md')}")
    return 1 if res["findings"] else 0


def cmd_show(a):
    p = Project(a.project)
    events = read_log(os.path.join(_run_dir(p, a.run), "events.jsonl"))
    convs = [e["conv"] for e in events if e["type"] == "conv_start"]
    if not a.conversation:
        findings = Checker(p).run(events)
        bad = {}
        for f in findings:
            bad.setdefault(f["conv"], []).append(f["code"])
        for c in convs:
            if a.failing and c not in bad:
                continue
            out(("FAIL  " if c in bad else "ok    ") + f"{c}" + ("   <- " + ", ".join(sorted(set(bad[c]))) if c in bad else ""))
        out(f"({len(bad)} of {len(convs)} conversations have findings)")
        return 0
    if a.conversation not in convs:
        raise SpecError(f"no conversation {a.conversation!r} in this run")
    out("\n".join(transcript(events, a.conversation, width=None if a.full else 100)))
    for f in Checker(p).run(events):
        if f["conv"] == a.conversation:
            out(f"PROBLEM {f['code']}: {f['detail']}")
    return 0


def cmd_replay(a):
    p = Project(a.project)
    events = read_log(os.path.join(_run_dir(p, a.run), "events.jsonl"))
    findings = [f for f in Checker(p).run(events) if f["conv"] == a.conversation]
    if a.code:
        findings = [f for f in findings if f["code"] == a.code or f["code"].startswith(a.code)]
    if not findings:
        raise SpecError(f"conversation {a.conversation!r} has no finding" + (f" matching {a.code!r}" if a.code else "")
                        + " in that run")
    case = replay.case_from_log(p, events, a.conversation)
    status = 0
    seen, todo = set(), []
    for f in sorted(findings, key=lambda f: report.rank(f["code"])):
        if (f["code"], f.get("expect_key")) not in seen:
            seen.add((f["code"], f.get("expect_key")))
            todo.append(f)
    exported = False
    for f in todo:
        code, key = f["code"], f.get("expect_key")
        rep, shown = replay.reproduce(p, a.target, case, code, a.n, key)
        out(f"{code}{' (' + key + ')' if key else ''}: happened in {rep['hits']} of {rep['n']} replays")
        if rep["hits"] and (a.shrink or a.export):
            short, info = replay.validated_shrink(p, a.target, case, code, key)
            mode = info["mode"]
            out(f"  shrunk from {sum('say' in s for s in case['steps'])} to "
                f"{sum('say' in s for s in short['steps'])} user messages ({info['checks']} trial runs"
                + {"full": "", "trim": "; a \"must not happen\" expectation: only what follows the violation and "
                                       "greetings before it may be cut; every message that says something, every "
                                       "no/yes, clock jump, outside change and the set-up are kept",
                   "inert": "; a \"did not happen\" expectation: only greetings, thanks and the like are cut, and "
                            "only if every other exchange stays exactly the same without them"}[mode] + ")")
            if not info["validated"]:
                out("  the shrunk script did not fail again when replayed, so the original script is kept")
            again = info.get("shown")
            if again:
                out("\n".join("  " + ln for ln in transcript(again["events"], short["id"], "changes")))
            if a.export and not exported:
                try:
                    out("  saved: " + replay.export_case(p, short, code, f["detail"], key=key, target=a.target))
                    exported = True
                except replay.ExportRefused as e:
                    out(f"  {e}")
        status = status or (1 if rep["hits"] else 0)
    return status


def cmd_compare(a):
    p = Project(a.project)
    cases = [] if a.population_only else p.load_cases(a.cases or None, a.only)
    personas = None
    if a.population or a.population_only:
        personas, _ = _personas(p, a, a.a)
    res = compare_mod.compare(p, a.a, a.b, cases or None, personas, a.reps)
    run_id, d = _next_run(p, a.name or None)
    _write(os.path.join(d, "compare.json"), json.dumps(res, indent=1))
    _write(os.path.join(d, "compare.md"), report.compare_markdown(res))
    _write(os.path.join(d, "events.jsonl"), "")
    out(f"{res['verdict']}: {len(res['regressions'])} new in B, {len(res['fixes'])} fixed in B, "
        f"noise floor {len(res['noise_floor'])}")
    out(f"Report: {os.path.join(d, 'compare.md')}")
    return 1 if res["verdict"].startswith("B is worse") else 0


def cmd_mutate(a):
    p = Project(a.project)
    approaches = [x.strip() for x in a.approaches.split(",") if x.strip()]
    for ap in approaches:
        if ap not in ("cases", "population"):
            raise SpecError("--approaches takes cases, population or both (comma-separated)")
    personas = None
    if "population" in approaches:
        personas, _ = _personas(p, a)
    rule = (p.config.get("compare") or {}).get("rule")

    def progress(ap, m, caught):
        if a.verbose:
            out(f"  {ap} {m['id']} {m['kind']} L{m['line']}: " + ("caught by " + ", ".join(caught) if caught else "MISSED"))

    src = None
    if a.file:
        base = p.config.get("target") or {}
        tdir = os.path.dirname(p.path(base["entry"].rsplit(":", 1)[0])) if ":" in str(base.get("entry", "")) else \
            p.path(base.get("cwd", "."))
        tried = [p.path(a.file), os.path.abspath(a.file), os.path.join(tdir, a.file)]
        src = next((x for x in tried if os.path.isfile(x)), None)
        if src is None:
            raise SpecError(f"mutate --file {a.file}: no such file (looked in the project folder, the current "
                            f"folder and the target's folder: {', '.join(dict.fromkeys(tried))})")
    res = mutate_mod.mutation_score(p, src, n=a.n, seed=a.seed, approaches=approaches,
                                    reps=a.reps, rule=rule, case_paths=a.cases or None, only=a.only,
                                    personas=personas, jobs=a.jobs, timeout=a.timeout, progress=progress)
    run_id, d = _next_run(p, a.name or None)
    _write(os.path.join(d, "mutation.json"), json.dumps(res, indent=1))
    _write(os.path.join(d, "mutation.md"), report.mutate_markdown(res))
    _write(os.path.join(d, "events.jsonl"), "")
    for ap, r in res["approaches"].items():
        out(f"{ap}: caught {r['caught']} of {r['total']} planted faults ({r['detection_power']:.0%})")
    out(f"missed by every approach: {len(res['missed_by_all'])}")
    out(f"Report: {os.path.join(d, 'mutation.md')}")
    return 0


def cmd_personas(a):
    p = Project(a.project)
    people = population.sample(p, seed=a.sim_seed)
    goals = p.population["goals"]
    out(f"{len(people)} simulated users cover every pair of trait values at least once.")
    for person in people[:a.limit]:
        s = population.Surface(person, goals[person["goal"]], p.vocab)
        first = s.render({"act": "open"})
        traits = {k: person[k] for k in population.traits_of(p)}
        out(f"  {person['pid']} user {person['user']} {traits}\n      opens with: {' / '.join(first)}")
    if a.out:
        _write(a.out, json.dumps(people, indent=1, default=str))
        out(f"wrote {a.out}")
    return 0


def cmd_serve_tools(a):
    p = Project(a.project)
    events = []
    box = ToolBox(p.new_world(), p.tools_spec, p.handlers,
                  lambda ev: (events.append(ev), out(json.dumps(ev, default=str)))[0])
    box.context = {"user": a.user}
    srv = ToolServer(box, port=a.port)
    out(f"fake tools at {srv.url}  (GET /tools, GET /clock, POST /call/<name>). Ctrl-C to stop.", )
    sys.stdout.flush()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.close()
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="poptest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"poptest {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp, target=True):
        sp.add_argument("--project", default=".", help="project folder (default: here or a parent)")
        if target:
            sp.add_argument("--target", help="override the target: file.py:Class, a URL, or a .json target config")

    def material(sp):
        sp.add_argument("--cases", nargs="*", help="case files or folders (default: the project's cases folder)")
        sp.add_argument("--only", nargs="*", help="only these case ids / families (id prefix* allowed)")
        sp.add_argument("--population", action="store_true", help="also run simulated users")
        sp.add_argument("--population-only", action="store_true")
        sp.add_argument("--budget", type=int, default=600, help="user messages to spend on simulated users")
        sp.add_argument("--sim-seed", type=int, default=0)
        sp.add_argument("--personas-file", help="reuse a personas.json from an earlier run")
        sp.add_argument("--name", help="name for the run folder")

    s = sub.add_parser("init", help="start a project")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--example", help="copy a worked example instead of the sample template (e.g. expense-agent)")
    s.add_argument("--bare", action="store_true", help="empty skeleton: no sample target, world, tools, rules or cases")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("validate", help="check the project files")
    common(s)
    s.add_argument("--cases", nargs="*")
    s.add_argument("--no-target", action="store_true", help="do not try to start the target")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("world", help="look at the sandbox data")
    common(s, target=False)
    s.add_argument("--entity")
    s.add_argument("--where", help="expression over rec, world, day")
    s.add_argument("--user", help="show one user and everything they own")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_world)

    s = sub.add_parser("say", help="send messages by hand")
    common(s)
    s.add_argument("--user", required=True)
    s.add_argument("--days-later", type=float, default=0, help="move the clock before the first message")
    s.add_argument("--hour", type=float, help="start at this hour of the day (0-23)")
    s.add_argument("--full", action="store_true", help="print tool results in full (default: first 100 characters)")
    s.add_argument("messages", nargs="+", help="messages in order; +2d, +13h or +30m moves the clock at that point")
    s.set_defaults(fn=cmd_say)

    s = sub.add_parser("run", help="run, check, replay, shrink, report")
    common(s)
    material(s)
    s.add_argument("--replays", type=int, default=5,
                   help="times to replay the example of each problem (0 = no replay, re-run or shrinking at all)")
    s.add_argument("--reruns", type=int, help="times to run every failing conversation again for the flake rule "
                                              "(default: poptest.json flake.reruns, 2; 0 = skip)")
    s.add_argument("--no-shrink", action="store_true")
    s.add_argument("--export", action="store_true", help="save shrunk failures under cases/regressions/")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("show", help="print a conversation from a run")
    common(s, target=False)
    s.add_argument("run", nargs="?", default="latest")
    s.add_argument("conversation", nargs="?")
    s.add_argument("--failing", action="store_true", help="list only conversations with findings")
    s.add_argument("--full", action="store_true", help="print tool results in full")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("replay", help="replay one failing conversation")
    common(s)
    s.add_argument("run")
    s.add_argument("conversation")
    s.add_argument("--code", help="which problem (default: all found in that conversation)")
    s.add_argument("-n", type=int, default=5)
    s.add_argument("--shrink", action="store_true")
    s.add_argument("--export", action="store_true", help="save the shrunk script once, under cases/regressions/")
    s.set_defaults(fn=cmd_replay)

    s = sub.add_parser("compare", help="release A versus release B")
    common(s, target=False)
    material(s)
    s.add_argument("--a", required=True, help="release A: file.py:Class, URL or .json target config")
    s.add_argument("--b", required=True, help="release B")
    s.add_argument("--reps", type=int, help="override the rule's repetitions")
    s.set_defaults(fn=cmd_compare)

    s = sub.add_parser("mutate", help="measure the suite's detection power")
    common(s, target=False)
    material(s)
    s.add_argument("--file", help="Python source file to plant faults in (default: a python target's entry file; "
                                  "required for http/cli targets). Relative to the project, the current folder "
                                  "or the target's folder.")
    s.add_argument("--n", type=int, default=40)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--reps", type=int, default=2)
    s.add_argument("--approaches", default="cases", help="cases, population, or cases,population")
    s.add_argument("--jobs", type=int, default=4)
    s.add_argument("--timeout", type=int, default=300, help="seconds per faulty copy")
    s.add_argument("--verbose", "-v", action="store_true")
    s.set_defaults(fn=cmd_mutate)

    s = sub.add_parser("personas", help="preview simulated users")
    common(s, target=False)
    s.add_argument("--sim-seed", type=int, default=0)
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_personas)

    s = sub.add_parser("serve-tools", help="run the fake-tools server on its own")
    common(s, target=False)
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--user", help="user to attribute calls to")
    s.set_defaults(fn=cmd_serve_tools)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a) or 0
    except SpecError as e:
        print(f"poptest: {e}", file=sys.stderr)
        return 2
    except BrokenPipeError:  # output piped into head, less, ...
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        # Never a raw traceback: say what failed and how to get the details.
        if os.environ.get("POPTEST_DEBUG"):
            raise
        import traceback
        tb = traceback.extract_tb(e.__traceback__)
        where = f"{os.path.basename(tb[-1].filename)}:{tb[-1].lineno}" if tb else "?"
        print(f"poptest: {a.cmd} failed: {type(e).__name__}: {e} (at {where}). This usually means a project file "
              f"has an unexpected shape: run 'poptest validate' for a file-by-file check, or set POPTEST_DEBUG=1 "
              f"to see the full traceback.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
