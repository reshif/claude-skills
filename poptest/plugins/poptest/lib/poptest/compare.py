"""Compare release A with release B on exactly the same cases / simulated users.

The decision rule is declared before the run (poptest.json -> compare.rule) and written into the
result. A is also run against itself: whatever the rule reports there is noise, not a regression.
"""
from collections import Counter

from .runner import execute
from .world import SpecError

DEFAULT_RULE = {"reps": 3, "min_b": 2, "max_a": 0}


def run_reps(project, target, cases=None, personas=None, reps=3, seed=None):
    """Run the same material `reps` times. Returns ({(conv, code): hits}, messages, conversations)."""
    units, turns, convs = Counter(), 0, []
    for k in range(reps):
        res = execute(project, target, cases=cases, personas=personas, run_id=f"rep{k}", seed=seed, sim_seed=k)
        turns += res["turns"]
        convs = res["convs"]
        for key in {(f["conv"], f["code"]) for f in res["findings"]}:
            units[key] += 1
    return units, turns, convs


def apply_rule(a, b, rule):
    """(conv, code) pairs that show in B at least min_b times and in A at most max_a times."""
    out = []
    for key, nb in sorted(b.items()):
        if nb >= rule["min_b"] and a.get(key, 0) <= rule["max_a"]:
            out.append({"conv": key[0], "code": key[1], "a_hits": a.get(key, 0), "b_hits": nb})
    return out


def get_rule(project, reps=None):
    declared = (project.config.get("compare") or {}).get("rule")
    if not declared:
        raise SpecError("declare the decision rule first: add to poptest.json\n"
                        '  "compare": {"rule": {"reps": 3, "min_b": 2, "max_a": 0}}\n'
                        "(a problem counts as new in B if it shows in at least min_b of B's runs and in at "
                        "most max_a of A's runs). Declaring it before looking at results is the point.")
    rule = dict(DEFAULT_RULE, **declared)
    if reps:
        rule["reps"] = reps
    if rule["min_b"] > rule["reps"]:
        raise SpecError("compare.rule: min_b cannot exceed reps")
    return rule


def compare(project, a, b, cases=None, personas=None, reps=None):
    rule = get_rule(project, reps)
    ua, turns_a, convs = run_reps(project, a, cases, personas, rule["reps"])
    ua2, _, _ = run_reps(project, a, cases, personas, rule["reps"])
    ub, turns_b, _ = run_reps(project, b, cases, personas, rule["reps"])
    regressions = apply_rule(ua, ub, rule)
    # In every row a_hits is the number of A runs with the problem and b_hits the number of B runs,
    # whichever direction the rule was applied in. (For the noise floor, "b" is A's second set.)
    fixes = [{"conv": x["conv"], "code": x["code"], "a_hits": x["b_hits"], "b_hits": x["a_hits"]}
             for x in apply_rule(ub, ua, rule)]
    noise = apply_rule(ua, ua2, rule)
    if len(regressions) > len(noise):
        verdict = "B is worse than A"
    elif len(fixes) > len(noise) and not regressions:
        verdict = "B is better than A"
    else:
        verdict = "no difference beyond noise"
    return {"rule": rule, "a": str(a), "b": str(b), "conversations": len(convs),
            "messages_per_run": turns_a // max(1, rule["reps"]),
            "regressions": regressions, "fixes": fixes, "noise_floor": noise, "verdict": verdict,
            "a_problem_pairs": len(ua), "b_problem_pairs": len(ub)}
