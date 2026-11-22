"""Reports: plain language for people (markdown), plain data for machines (JSON)."""
from .checks import humanise
from .replay import ExportRefused, case_from_log, export_case, reproduce, rerun, validated_shrink
from .runner import noise_stats, transcript

CATALOG = {
    "crash": ("The system crashed or gave an error instead of an answer",
              "The user is left with an error or with silence, and whatever they were doing is lost."),
    "privacy_leak": ("One user was shown another user's private information",
                     "Private data reached someone who must never see it. This is the kind of failure that "
                     "ends in a breach report."),
    "record_detail_leak": ("One user was shown details of a record that belongs to someone else",
                           "Anyone who can guess or mistype a record number can read other people's data."),
    "unconfirmed_action": ("An action was taken without a clear yes from the user",
                           "The system changed something real when the user had not agreed, or had said no."),
    "confirm_mismatch": ("The user agreed to one thing and the system did another",
                         "The confirmation step is there to prevent exactly this: the user's yes was used for "
                         "something they were never shown."),
    "false_claim": ("The system said it had done something that it had not done",
                    "The user leaves believing the job is done. Nothing has happened."),
    "wrong_user_change": ("Serving one user, the system changed data that belongs to another user",
                          "One person's request altered someone else's account or records."),
    "wrong_user_access": ("The system used the wrong user's identity for an operation",
                          "Data was read or written under another user's name."),
    "wrong_fact": ("The system stated something that does not match the real data",
                   "Users act on what they are told. A wrong amount, date or status sends them the wrong way."),
    "noise_side_effect": ("A turn that the system answered with a \"please repeat\" reply changed data anyway",
                          "That reply is declared as harmless noise that clients answer by sending the message "
                          "again. If the first attempt already acted, the resend can act twice."),
    "rule": ("A rule of the product was broken", "This rule was declared as something that must always hold."),
    "expect": ("A written test case did not get the result it expected",
               "The case describes what the product should do in this situation; it did something else."),
    "goal_not_met": ("A simulated user could not get a legitimate task done",
                     "A reasonable request ended without the result the user was entitled to."),
}
EXPECT_TITLES = {
    "calls": "An action a test case expects did not happen",
    "no_calls": "An action happened that a test case says must not happen",
    "world": "The data ended up different from what a test case expects",
    "unchanged": "Data changed that a test case says must stay as it was",
    "reply_contains": "A reply did not contain what a test case expects",
    "reply_matches": "A reply did not contain what a test case expects",
    "reply_not_contains": "A reply contained something a test case says must not be shown",
    "reply_not_matches": "A reply contained something a test case says must not be shown",
}
ORDER = ["privacy_leak", "record_detail_leak", "wrong_user_change", "wrong_user_access", "unconfirmed_action",
         "confirm_mismatch", "noise_side_effect", "rule", "false_claim", "wrong_fact", "crash", "expect",
         "goal_not_met"]
FLAKE_DEFAULT = {"min_hits": 2, "reruns": 2, "max_conversations": 300}
MODE_TEXT = {
    "trim": "This is a \"must not happen\" expectation, so only what came after the violation and greetings before "
            "it were cut: every message that says something, every yes and no, clock jump, outside change, other "
            "window and the set-up were kept.",
    "inert": "This is a \"did not happen\" expectation, so only greetings, thanks and the like were cut, and only "
             "where every other exchange stayed exactly the same without them.",
}


def rank(code):
    h = code.split(":")[0]
    return ORDER.index(h) if h in ORDER else 99


def explain(project, code, finding=None):
    head, _, tail = code.partition(":")
    title, why = CATALOG.get(head, (code, ""))
    rules = project.rules or {}
    if head == "rule":
        # every custom rule gets its own headline: title/message in rules.json, the title given to
        # ctx.fail or the RULES table in rules.py, else the rule id in words
        named = None
        for r in list(rules.get("invariants", [])) + list(rules.get("facts", [])):
            if r.get("id") == tail:
                named = r.get("title") or r.get("message")
                why = r.get("why", why)
        declared = getattr(project.rules_module, "RULES", None) if project.rules_module else None
        if not named and isinstance(declared, dict) and tail in declared:
            d = declared[tail]
            named = d if isinstance(d, str) else (d or {}).get("title")
            if isinstance(d, dict) and d.get("why"):
                why = d["why"]
        if not named and finding and finding.get("title"):
            named = finding["title"]
        title = named or f"Rule broken: {humanise(tail)}"
        if finding and finding.get("why"):
            why = finding["why"]
    elif head in ("unconfirmed_action", "confirm_mismatch", "false_claim") and tail:
        label = rules.get("actions", {}).get(tail, {}).get("label", tail)
        title = f"{title} ({label})"
    elif head == "wrong_fact" and tail:
        title = f"{title} ({tail})"
        if finding and finding.get("why"):
            why = finding["why"]
    elif head in ("privacy_leak", "record_detail_leak") and tail:
        title = f"{title} ({tail.replace('.', ': ')})"
    elif head == "expect":
        k = tail[5:] if tail.startswith("step_") else tail
        title = EXPECT_TITLES.get(k.replace("last_reply", "reply"), title)
    elif head == "goal_not_met" and tail:
        title = f"{title} ({tail})"
    elif head == "noise_side_effect" and tail:
        title = f"{title} ({tail})"
    return title, why


def _n_msgs(events, conv):
    return sum(1 for e in events if e.get("conv") == conv and e["type"] == "user_msg" and not e.get("resend"))


def trigger_text(trigger):
    return " → ".join(trigger) if trigger else "plain request"


def incidents(findings):
    """Per conversation, put together the findings that are one failure seen by several checks:
    everything about the same tool, and everything raised on the same reply. A case's own
    expectations join the failure they echo. Returns a list of
    {"conv", "tool", "action", "trigger", "primary": finding, "findings": [...]}."""
    by_conv = {}
    for f in findings:
        by_conv.setdefault(f["conv"], []).append(f)
    out = []
    for conv, fs in by_conv.items():
        anchors, loose = {}, []
        for f in fs:
            soft = f["code"].startswith(("expect:", "goal_not_met"))
            if f.get("tool"):
                anchors.setdefault(("tool", f["tool"]), []).append(f)
            elif not soft:
                anchors.setdefault(("at", f.get("seq"), f.get("session")), []).append(f)
            else:
                loose.append(f)
        # an anchor made only of expectations is not an anchor for other expectations to join
        hard = [k for k, v in anchors.items() if any(not x["code"].startswith(("expect:", "goal_not_met")) for x in v)]
        for f in loose:
            if len(hard) == 1:
                anchors[hard[0]].append(f)
            elif not hard and len(anchors) == 1:
                next(iter(anchors.values())).append(f)
            else:
                anchors.setdefault(("code", f["code"]), []).append(f)
        for key, group in anchors.items():
            primary = min(group, key=lambda f: (rank(f["code"]), f.get("seq") or 0))
            out.append({"conv": conv, "tool": primary.get("tool") or (key[1] if key[0] == "tool" else None),
                        "action": primary.get("action"), "trigger": list(primary.get("trigger") or []),
                        "primary": primary, "findings": group})
    return out


def cluster(project, findings):
    """Group findings by root cause: incidents with the same primary check, the same tool / action
    and the same trigger steps are one problem, whatever number of checks and conversations saw it."""
    groups = {}
    for inc in incidents(findings):
        if inc["primary"]["code"].startswith("goal_not_met"):
            # simulated users wander: how they got there is their own doing, not a signature
            inc["trigger"] = ["(varies: simulated users)"]
        key = (inc["primary"]["code"], inc["tool"], inc["action"], tuple(inc["trigger"]))
        same = next((i for i in groups.get(key, []) if i["conv"] == inc["conv"]), None)
        if same:   # the same failure twice in one conversation is still one conversation
            same["findings"].extend(inc["findings"])
        else:
            groups.setdefault(key, []).append(inc)
    problems = []
    for (code, tool, action, trigger), incs in groups.items():
        first = incs[0]["primary"]
        title, why = explain(project, code, first)
        codes, examples, seen = {}, [], set()
        for inc in incs:
            for c in {f["code"] for f in inc["findings"]}:
                codes[c] = codes.get(c, 0) + 1
            for f in sorted(inc["findings"], key=lambda f: (rank(f["code"]), f.get("seq") or 0)):
                line = f["detail"].splitlines()[0] if f["detail"] else ""
                if (f["code"], line) not in seen:
                    seen.add((f["code"], line))
                    examples.append({"conversation": inc["conv"], "code": f["code"], "detail": line})
        convs = list(dict.fromkeys(inc["conv"] for inc in incs))
        problems.append({"code": code, "title": title, "why": why, "tool": tool, "action": action,
                         "trigger": list(trigger), "trigger_text": trigger_text(trigger),
                         "codes": dict(sorted(codes.items(), key=lambda kv: (rank(kv[0]), kv[0]))),
                         "conversations": convs, "count": len(convs), "detail": first["detail"],
                         "examples": examples, "example": None, "replay": None, "flaky": False,
                         "_incs": incs})
    problems.sort(key=lambda p: (rank(p["code"]), p["code"], -p["count"], p["trigger"]))
    for i, p in enumerate(problems, 1):
        p["id"] = f"P{i}"
    return problems


def flake_rule(project, replays):
    """The declared rule for calling a finding reproducible (poptest.json "flake")."""
    rule = dict(FLAKE_DEFAULT, **(project.config.get("flake") or {}))
    rule["replays"] = replays
    rule["min_hits"] = max(1, min(int(rule["min_hits"]), replays)) if replays else 0
    return rule


def triage(project, target, events, findings, replays=5, do_shrink=True, export=False, max_problems=40,
           progress=None, reruns=None, rerun_progress=None):
    """Group findings into problems by root cause; re-run every failing conversation so each
    finding has its own reproduction count; replay and shrink one example of each problem; and
    apply the flake rule: a problem is headlined only if it comes back.

    Flake rule (poptest.json "flake": {"min_hits": 2, "reruns": 2}): the example conversation is
    replayed `replays` times and must show the problem at least min_hits times; every other failing
    conversation is run again `reruns` times and counts as reproduced if it shows it at least once.
    replays=0 skips all of it (nothing is then marked either way)."""
    problems = cluster(project, findings)
    rule = flake_rule(project, replays)
    if reruns is not None:
        rule["reruns"] = reruns
    cases, again, rerun_done = {}, {}, False
    if replays > 0 and rule["reruns"] > 0:
        convs = list(dict.fromkeys(c for p in problems[:max_problems] for c in p["conversations"]))
        for c in convs[:int(rule["max_conversations"])]:
            cases[c] = case_from_log(project, events, c)
        if len(cases) > 1:   # a single failing conversation is covered by its replays below
            again = rerun(project, target, list(cases.values()), int(rule["reruns"]), rerun_progress)
            rerun_done = True
    for n, prob in enumerate(problems):
        incs = prob.pop("_incs")
        code = prob["code"]
        back = {}
        if rerun_done:
            for inc in incs:
                if inc["conv"] in cases:
                    back[inc["conv"]] = max((again.get((inc["conv"], f["code"], f.get("expect_key")), 0)
                                             for f in inc["findings"]), default=0)
            prob["rerun"] = {"n": rule["reruns"], "conversations": back,
                             "came_back": sum(1 for v in back.values() if v > 0),
                             "did_not": sum(1 for v in back.values() if v == 0),
                             "not_rerun": prob["count"] - len(back)}
        if n < max_problems and replays > 0:
            # the example: the shortest conversation, preferring one that came back when re-run
            inc = min(incs, key=lambda i: (back.get(i["conv"], 1) == 0, _n_msgs(events, i["conv"])))
            conv, f0 = inc["conv"], inc["primary"]
            key, detail = f0.get("expect_key"), f0["detail"]
            case = cases.get(conv) or case_from_log(project, events, conv)
            rep, shown = reproduce(project, target, case, code, replays, key)
            ex = {"conversation": conv, "detail": detail, "original_messages": _n_msgs(events, conv)}
            short, shown_short, info = case, shown, {}
            if rep["hits"] and do_shrink:
                short, info = validated_shrink(project, target, case, code, key)
                shown_short = info.pop("shown", None) or shown
            if shown_short:
                ex["transcript"] = transcript(shown_short["events"], short["id"], "changes")
                ex["detail"] = next((f["detail"] for f in shown_short["findings"]
                                     if f["code"] == code and (key is None or f.get("expect_key") == key)), detail)
            else:
                ex["transcript"] = transcript(events, conv, "changes")
            ex["short_messages"] = sum(1 for s in short["steps"] if "say" in s)
            ex["shrink_mode"] = info.get("mode")
            ex["case"] = short
            prob["flaky"] = rep["hits"] < rule["min_hits"]
            if export and rep["hits"] and not prob["flaky"]:
                try:
                    ex["saved_as"] = export_case(project, short, code, ex["detail"], key=key, target=target)
                except ExportRefused as e:
                    ex["not_saved"] = str(e)
            prob.update(example=ex, replay=rep, detail=ex["detail"])
        if progress:
            progress(prob)
    return problems


def build(project, run_id, events, findings, warnings, problems, info=None):
    convs = [e for e in events if e["type"] == "conv_start"]
    fams = {}
    for e in convs:
        key = e.get("family") or ("simulated user" if e.get("kind") == "persona" else "unlabelled")
        fams[key] = fams.get(key, 0) + 1
    failing = {f["conv"] for f in findings}
    by_conv = {}
    for f in findings:
        by_conv.setdefault(f["conv"], {"codes": [], "problems": []})
        if f["code"] not in by_conv[f["conv"]]["codes"]:
            by_conv[f["conv"]]["codes"].append(f["code"])
    for p in problems:
        for c in p["conversations"]:
            if c in by_conv and p.get("id") and p["id"] not in by_conv[c]["problems"]:
                by_conv[c]["problems"].append(p["id"])
    firm = [p for p in problems if not p["code"].startswith("goal_not_met") and not p.get("flaky")]
    summary = {"conversations": len(convs),
               "user_messages": sum(1 for e in events if e["type"] == "user_msg" and not e.get("resend")),
               "conversations_with_problems": len(failing), "problem_kinds": len(problems),
               "problems_reproduced": len(firm), "problems_not_reproduced": sum(1 for p in problems if p.get("flaky")),
               "findings": len(findings), "by_family": fams, **(info or {})}
    noise = noise_stats(events)
    if noise["noise_replies"]:
        summary["noise"] = noise
    return {
        "project": project.name, "run": run_id, "summary": summary,
        "problems": problems, "by_conversation": by_conv, "findings": findings, "warnings": warnings,
    }


def _replay_cell(p):
    r = p.get("replay")
    return f"{r['hits']} of {r['n']}" if r else "not replayed"


def markdown(rep):
    s = rep["summary"]
    probs = rep["problems"]
    soft = [p for p in probs if p["code"].startswith("goal_not_met")]
    flaky = [p for p in probs if p.get("flaky") and p not in soft]
    firm = [p for p in probs if p not in soft and p not in flaky]
    L = [f"# Test report: {rep['project']}", ""]
    L.append(f"{s['conversations']} conversations were run against the system ({s['user_messages']} user messages).")
    if not probs:
        L += ["", "**No problems were found by the checks.** That is only as strong as the checks and cases: "
                  "run `poptest mutate` to see how many planted faults this suite would catch."]
    else:
        n_find = s.get("findings", len(rep.get("findings", [])))
        L += ["", f"**{len(firm)} problem(s) found**, in {s['conversations_with_problems']} of "
                  f"{s['conversations']} conversations. The checks raised {n_find} finding(s); they are grouped here "
                  f"by root cause (same check, same action, same steps leading to it), so one problem is listed once "
                  f"however many checks and conversations saw it."
              + (f" {len(flaky)} more group(s) did not come back when the same messages were sent again; they are "
                 f"listed under \"Did not reproduce\" and are not counted as problems." if flaky else "")
              + (f" Plus {len(soft)} lower-confidence signal(s), listed at the end." if soft else "")]
        if firm:
            L += ["", "| # | Problem | Action | Steps leading to it | Conversations | Happens again on replay | Also seen as |",
                  "|---|---|---|---|---|---|---|"]
            for i, p in enumerate(firm, 1):
                also = ", ".join(f"{c} ({n})" for c, n in p.get("codes", {}).items() if c != p["code"]) or "-"
                act = p.get("action") or p.get("tool") or "-"
                L.append(f"| {i} | {p['title']} | {act} | {p.get('trigger_text', '-')} | {p['count']} | "
                         f"{_replay_cell(p)} | {also} |")
    for i, p in enumerate(firm, 1):
        L += ["", f"## {i}. {p['title']}", ""]
        L += _problem(p, s)
    if flaky:
        L += ["", "## Did not reproduce", "",
              "These findings showed once and did not come back when exactly the same messages were sent again "
              "(the rule for \"comes back\" was fixed before the run). They depend on chance, on timing or on what "
              "other conversations left behind. Read them, but do not report them as bugs without a script that "
              "reproduces.", ""]
        for p in flaky:
            L += [f"### {p['title']}", ""] + _problem(p, s)
    if soft:
        L += ["", "## Lower confidence: simulated users who did not get what they came for", "",
              "These depend on how the simulated user behaved, so read the conversation before acting on them.", ""]
        for p in soft:
            L += [f"### {p['title']}", ""] + _problem(p, s)
    L += ["", "## What was run", ""]
    for fam, n in sorted(s["by_family"].items()):
        L.append(f"- {fam}: {n} conversation(s)")
    if s.get("population"):
        pop = s["population"]
        L.append(f"- Simulated users: {pop.get('personas')} users over {pop.get('waves')} round(s), "
                 f"{pop.get('distinct_paths')} different conversation paths")
    if s.get("noise"):
        nz = s["noise"]
        L += ["", "## Replies declared as noise", "",
              f"The system answered {nz['noise_replies']} of {nz['sends']} sent messages ({nz['rate']:.1%}) with a "
              f"reply that this project declares as random noise. Each of those messages was sent again and only the "
              f"real answer was checked. In {nz['with_tool_calls']} of those turns the system made a call to its "
              f"backend, and in {nz['with_data_changes']} it changed data"
              + (" (reported above)." if nz["with_data_changes"] else ", so the noise turns had no side effects.")]
    L += ["", "## How to read this", "",
          "- Every problem above was detected by a check written in code against the true data in the test "
          "sandbox, not by an opinion. Each one comes with the shortest script found that shows it.",
          "- Findings are grouped by root cause. \"Also seen as\" lists the other checks and case expectations that "
          "noticed the same failure in the same conversations.",
          "- \"Happens again on replay\" is how many times the same messages produced the same problem when sent "
          "again. Systems built on language models do not always answer the same way. A problem is only listed as "
          "found when it comes back; every other failing conversation was also run again and is counted.",
          "- Counts describe this set of test conversations. They are not a forecast of how often real users "
          "will hit the problem. Use them to compare one release with another.",
          "- This tool does not judge whether answers are well written, helpful or correct in general."]
    if rep.get("warnings"):
        L += ["", "## Rules that could not be evaluated", ""] + [f"- {w}" for w in rep["warnings"]]
    return "\n".join(L) + "\n"


def _problem(p, s):
    what = p["detail"][:1].upper() + p["detail"][1:]
    L = [f"**What happened.** {what}" + ("" if what.endswith((".", "?", "!", ")", "\"")) else "."), ""]
    how = f"**How often.** In {p['count']} of {s['conversations']} conversations."
    r, ex = p.get("replay"), p.get("example")
    if r:
        how += f" The same messages were sent again {r['n']} times: the problem showed {r['hits']} time(s)."
        if r["hits"] == 0:
            how += " It did not come back, so it depends on timing, on other users' activity, or on chance."
    rr = p.get("rerun")
    if rr and (rr["came_back"] + rr["did_not"]) > 1:
        how += (f" Each of these conversations was also run again {rr['n']} time(s): {rr['came_back']} showed it "
                f"again, {rr['did_not']} did not" + (f", {rr['not_rerun']} were not re-run" if rr["not_rerun"] else "") + ".")
        gone = [c for c, v in rr["conversations"].items() if v == 0]
        if gone and rr["came_back"]:
            how += " Did not come back: " + ", ".join(gone[:8]) + (f" and {len(gone) - 8} more" if len(gone) > 8 else "") + "."
    L += [how, ""]
    codes = p.get("codes") or {}
    if len(codes) > 1:
        L += ["**Seen by.** " + "; ".join(f"`{c}` in {n} conversation(s)" for c, n in codes.items()), ""]
    if p.get("tool") or p.get("trigger") is not None:
        bits = []
        if p.get("tool"):
            bits.append(f"action `{p.get('action') or p['tool']}`" + (f" (tool `{p['tool']}`)" if p.get("action") else ""))
        bits.append(f"steps leading to it: {p.get('trigger_text', 'plain request')}")
        L += ["**Common to all of them.** " + "; ".join(bits) + ".", ""]
    exs = p.get("examples") or []
    if len(exs) > 1:
        L += [f"**All distinct examples** ({len(exs)}; first line of each):", ""]
        L += [f"- `{e['conversation']}` [{e['code']}] {e['detail']}" for e in exs[:25]]
        if len(exs) > 25:
            L.append(f"- and {len(exs) - 25} more in report.json")
        L.append("")
    if ex:
        cut = ""
        if ex["short_messages"] < ex["original_messages"]:
            cut = f" (cut down from {ex['original_messages']} user messages to {ex['short_messages']})"
        L += [f"**Shortest way to see it**{cut}:", "", "```"] + ex["transcript"] + ["```", ""]
        if ex.get("shrink_mode") in MODE_TEXT:
            L += [MODE_TEXT[ex["shrink_mode"]], ""]
        if ex.get("saved_as"):
            L += [f"Saved as a permanent test case: `{ex['saved_as']}`", ""]
        if ex.get("not_saved"):
            L += [f"Not saved as a test case: {ex['not_saved']}", ""]
    if p.get("why"):
        L += [f"**Why it matters.** {p['why']}", ""]
    shown = ", ".join(p["conversations"][:12]) + (f" and {len(p['conversations']) - 12} more (all in report.json)"
                                                  if len(p["conversations"]) > 12 else "")
    L += [f"**Where.** {shown}"]
    return L


def compare_markdown(res):
    r = res["rule"]
    L = ["# Release comparison", "", f"- A: `{res['a']}`", f"- B: `{res['b']}`",
         f"- {res['conversations']} conversations, each run {r['reps']} times on A, on A again, and on B.",
         f"- Rule fixed before the run: a problem is new in B when it shows in at least {r['min_b']} of {r['reps']} "
         f"B runs and in at most {r['max_a']} of {r['reps']} A runs.", "",
         f"## Result: {res['verdict']}", "",
         f"- New problems in B: **{len(res['regressions'])}**",
         f"- Problems in A that B no longer has: **{len(res['fixes'])}**",
         f"- Noise floor (A compared with itself by the same rule): **{len(res['noise_floor'])}**", ""]
    if len(res["noise_floor"]):
        L += ["A compared with itself already shows differences. Treat a count of new problems at or below the "
              "noise floor as no evidence of a change; raise the number of repetitions for a sharper answer.", ""]
    n = r["reps"]
    for title, rows, a, b in (("New problems in B", res["regressions"], "A", "B"),
                              ("Fixed in B (A has the problem, B does not)", res["fixes"], "A", "B"),
                              ("Noise: A versus A", res["noise_floor"], "A, first set of", "A, second set of")):
        if rows:
            L += [f"## {title}", "", f"| Conversation | Problem | {a} runs with the problem (of {n}) | "
                                     f"{b} runs with the problem (of {n}) |", "|---|---|---|---|"]
            L += [f"| {x['conv']} | {x['code']} | {x['a_hits']} | {x['b_hits']} |" for x in rows[:60]]
            if len(rows) > 60:
                L.append(f"| ... | {len(rows) - 60} more | | |")
            L.append("")
    return "\n".join(L) + "\n"


def mutate_markdown(res):
    from .mutate import KIND_TEXT
    L = ["# How good is this test suite at catching faults?", "",
         f"{len(res['mutants'])} faulty copies of `{res.get('file_abs') or res['file']}` were made, each with one "
         f"small planted fault, and run through the tests ({res['rule']['reps']} times each). A fault counts as caught when a problem "
         f"shows in at least {res['rule']['min_b']} of those runs that the unmodified system does not show.", ""]
    L += ["| Approach | Conversations | Faults caught | Detection power |", "|---|---|---|---|"]
    for ap, a in res["approaches"].items():
        L.append(f"| {'written cases' if ap == 'cases' else 'simulated users'} | {a['conversations']} | "
                 f"{a['caught']} of {a['total']} | {a['detection_power']:.0%} |")
    for ap, a in res["approaches"].items():
        L += ["", f"## By kind of fault: {'written cases' if ap == 'cases' else 'simulated users'}", "",
              "| Kind of fault | Caught | Planted |", "|---|---|---|"]
        for k, v in sorted(a["by_kind"].items()):
            L.append(f"| {KIND_TEXT.get(k, k)} | {v['caught']} | {v['total']} |")
        if a.get("clean_problem_pairs"):
            L += ["", f"Note: the unmodified system already shows {a['clean_problem_pairs']} problem(s) in this "
                      "approach; faults that only repeat those do not count as caught."]
    L += ["", f"## Faults no approach caught ({len(res['missed_by_all'])})", ""]
    if not res["missed_by_all"]:
        L.append("None.")
    for m in res["missed_by_all"]:
        L.append(f"- line {m['line']}: {KIND_TEXT.get(m['kind'], m['kind'])}: `{m['source'][:100]}`  ({m['id']})")
    L += ["", "Each missed fault is either harmless (the changed code behaves the same from outside) or a gap: "
              "a situation no case creates, or a result no check looks at. Read the line, decide which, and add "
              "a case or a rule for the gaps.", "",
          "Detection power is measured on small code faults in this file. It says little about faults of other "
          "kinds, such as a changed prompt or a model swap."]
    return "\n".join(L) + "\n"
