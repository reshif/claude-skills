"""Regression tests for poptest 1.1, one class per item of the release, each test tied to a problem
that first-time users reported with 1.0.  Run:  python3 -m unittest discover -s tests
The target is tests/fixtures/shop: a small shop/helpdesk assistant with switchable faults whose
confirmation wording has no question mark and whose close/reopen share one backend tool."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "lib"))

from poptest import compare, mutate, population, replay, report  # noqa: E402
from poptest.adapters import pick_port, port_in_use  # noqa: E402
from poptest.checks import Checker, match_args, mentions, minor_forms  # noqa: E402
from poptest.project import Project, normalise_case  # noqa: E402
from poptest.runner import Driver, execute, noise_stats, transcript  # noqa: E402
from poptest.tools import ToolBox, ToolError, ToolServer, call_ok  # noqa: E402
from poptest.world import VERSION, SpecError, World, safe_eval  # noqa: E402

SHOP = os.path.join(HERE, "fixtures", "shop")
BIN = os.path.join(PLUGIN, "bin", "poptest")
ASK = " Reply yes to confirm or no to cancel."


def T(cls):
    return f"bot.py:{cls}"


def case(steps, cid="t", user="U1", **kw):
    return normalise_case(dict({"id": cid, "user": user, "steps": steps}, **kw))


def run(project, steps, target=None, **kw):
    res = execute(project, target, cases=[case(steps, **kw)])
    return res, sorted({f["code"] for f in res["findings"]})


def clone(tmp, edit=None, name="proj"):
    """A private copy of the shop fixture; `edit` maps file name -> function(json) -> json."""
    d = os.path.join(tmp, name)
    shutil.copytree(SHOP, d, ignore=shutil.ignore_patterns("__pycache__", "runs"))
    for fname, fn in (edit or {}).items():
        path = os.path.join(d, fname)
        data = load(path) if os.path.exists(path) else {}
        with open(path, "w") as f:
            json.dump(fn(data), f)
    return d


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load(path):
    return json.loads(read(path))


def sh(*args, cwd=None, env=None):
    r = subprocess.run([sys.executable, BIN, *args], cwd=cwd, capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, **(env or {})))
    return r.returncode, r.stdout + r.stderr


class ShopCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project(SHOP)
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


# ============================================================================== 1. noise + flake
class TestNoiseReplies(ShopCase):
    """Feedback: every tester of a target with a spec'd 3% "could you repeat that?" reply had to
    write their own retry wrapper, and lost coverage of that branch by doing so."""

    def test_noise_reply_is_resent_recorded_and_kept_out_of_the_checks(self):
        res, codes = run(self.p, ["hello", "close T-1", "yes", "time"], T("Noisy"),
                         expect={"calls": [{"tool": "update_ticket", "count": 1}],
                                 "last_reply_contains": ["It is"], "reply_not_contains": ["repeat that"],
                                 "reply_contains": ["T-1 has been closed"]})
        self.assertEqual(codes, [], res["findings"])
        ev = res["events"]
        noise = [e for e in ev if e["type"] == "noise"]
        self.assertEqual(len(noise), 1)
        self.assertEqual((noise[0]["calls"], noise[0]["changes"], noise[0]["attempt"]), ([], [], 0))
        self.assertEqual([e["text"] for e in ev if e["type"] == "bot_msg" and e.get("noise")],
                         ["Sorry, could you repeat that?"])
        resent = [e for e in ev if e["type"] == "user_msg" and e.get("resend")]
        self.assertEqual([e["text"] for e in resent], ["yes"])
        self.assertEqual(res["turns"], 4, "a resend is not a new user message")
        self.assertEqual(res["noise_turns"], 1)
        self.assertEqual(noise_stats(ev), {"sends": 5, "noise_replies": 1, "rate": 0.2, "with_tool_calls": 0,
                                           "with_data_changes": 0})
        self.assertIn("    (that reply is declared noise: the same message was sent again)", transcript(ev, "t"))

    def test_without_the_declaration_the_same_case_derails(self):
        off = {"adapter": "python", "entry": T("Noisy"), "noise": {"replies": []}}
        res, codes = run(self.p, ["hello", "close T-1", "yes"], off, expect={"calls": ["update_ticket"]})
        self.assertEqual(codes, ["expect:calls"])
        self.assertFalse([e for e in res["events"] if e["type"] == "noise"])

    def test_a_noise_turn_that_changed_data_is_a_finding(self):
        res, codes = run(self.p, ["close T-1", "yes"], T("NoisyActs"))
        self.assertIn("noise_side_effect:update_ticket", codes)
        f = next(f for f in res["findings"] if f["code"].startswith("noise_side_effect"))
        self.assertIn("declared as a noise reply", f["detail"])
        self.assertIn("tickets T-1", f["detail"])
        self.assertEqual(noise_stats(res["events"])["with_data_changes"], 1)

    def test_a_reply_that_never_stops_matching_is_the_real_answer(self):
        # noise is random; something that comes back max_resends times in a row is the product talking
        res, codes = run(self.p, ["hello"], T("AlwaysNoise"), expect={"last_reply_contains": ["could you repeat that"]})
        self.assertEqual(codes, [])
        self.assertEqual(len([e for e in res["events"] if e["type"] == "noise"]), 3)
        self.assertEqual(len([e for e in res["events"] if e["type"] == "bot_msg" and not e.get("noise")]), 1)

    def test_simulated_users_never_see_the_noise_reply(self):
        d = Driver(self.p, T("Noisy"))
        try:
            sc = d.new_scope("x")
            d.start_conv(sc, "c", "case", "U1")
            d.open_session(sc, "c", "s", "U1")
            seen = [d.say(sc, "c", "s", "U1", "hello") for _ in range(6)]
        finally:
            d.close()
        self.assertEqual(seen, [["Hello."]] * 6)
        self.assertEqual(d.noise_turns, 2)   # every third send; the resends count as sends

    def test_noise_is_handled_in_replays_too(self):
        res, _ = run(self.p, ["hello", "close T-1", "yes"], T("Noisy"), cid="n")
        c = replay.case_from_log(self.p, res["events"], "n")
        self.assertEqual([s["say"] for s in c["steps"]], ["hello", "close T-1", "yes"])

    def test_bad_noise_configuration_is_a_clear_error(self):
        for bad in ({"replies": ["(unclosed"]}, {"replies": ["x"], "retry": 3}, {"max_resends": "many", "replies": ["x"]}, 7):
            with self.assertRaises(SpecError, msg=bad):
                execute(self.p, {"adapter": "python", "entry": T("Shop"), "noise": bad}, cases=[case(["hello"])])


class TestFlakeRule(ShopCase):
    """Feedback: "'expect:calls, 7 conversations, replay 5/5' contained one real error plus six
    glitch flakes. The 5/5 applied only to the shrunk representative."."""

    def setUp(self):
        self.marker = os.path.join(self.tmp, f"flake-{self._testMethodName}")
        os.environ["SHOP_FLAKE_FILE"] = self.marker

    def tearDown(self):
        os.environ.pop("SHOP_FLAKE_FILE", None)

    def test_a_finding_that_does_not_come_back_is_not_headlined(self):
        cases = [case(["flake"], "once"), case(["show T-7"], "steady")]
        res = execute(self.p, cases=cases)
        self.assertEqual({f["code"] for f in res["findings"]}, {"privacy_leak:users.account", "record_detail_leak:tickets"})
        probs = report.triage(self.p, None, res["events"], res["findings"], replays=4)
        by = {p["code"]: p for p in probs}
        self.assertTrue(by["privacy_leak:users.account"]["flaky"])
        self.assertEqual(by["privacy_leak:users.account"]["replay"]["hits"], 0)
        self.assertFalse(by["record_detail_leak:tickets"]["flaky"])
        rep = report.build(self.p, "r", res["events"], res["findings"], [], probs)
        self.assertEqual((rep["summary"]["problems_reproduced"], rep["summary"]["problems_not_reproduced"]), (1, 1))
        md = report.markdown(rep)
        self.assertIn("**1 problem(s) found**", md)
        head, _, tail = md.partition("## Did not reproduce")
        self.assertTrue(tail, "flaky findings get their own section")
        self.assertNotIn("private information", head.split("## 1.")[0], "not in the headline table")
        self.assertIn("One user was shown another user's private information", tail)

    def test_every_failing_conversation_gets_its_own_reproduction_count(self):
        cases = [case(["leak"], "a"), case(["flake"], "b"), case(["leak"], "c")]
        res = execute(self.p, cases=cases)
        probs = report.triage(self.p, None, res["events"], res["findings"], replays=3)
        self.assertEqual(len(probs), 1, "one root cause")
        p = probs[0]
        self.assertEqual(p["count"], 3)
        self.assertEqual(p["rerun"]["conversations"], {"a": 2, "b": 0, "c": 2})
        self.assertEqual((p["rerun"]["came_back"], p["rerun"]["did_not"]), (2, 1))
        self.assertIn(p["example"]["conversation"], ("a", "c"), "the example is one that reproduces")
        self.assertFalse(p["flaky"])
        md = report.markdown(report.build(self.p, "r", res["events"], res["findings"], [], probs))
        self.assertIn("2 showed it again, 1 did not", md)
        self.assertIn("Did not come back: b.", md)

    def test_the_rule_is_declared_and_min_hits_is_respected(self):
        self.assertEqual(report.flake_rule(self.p, 5)["min_hits"], 2)
        self.assertEqual(report.flake_rule(self.p, 1)["min_hits"], 1)
        self.assertEqual(report.flake_rule(self.p, 0)["min_hits"], 0)
        res = execute(self.p, cases=[case(["show T-7"], "steady")])
        probs = report.triage(self.p, None, res["events"], res["findings"], replays=0)
        self.assertIsNone(probs[0]["replay"])
        self.assertFalse(probs[0]["flaky"], "nothing is called flaky when replay is switched off")


# ============================================================================== 2. confirmation
class TestConfirmation(ShopCase):
    """Feedback: "the confirmation check is unusable unless the question contains '?'" (3 testers),
    "needs_confirmation is per tool, but close/reopen/escalate share update_ticket" (3 testers),
    "amount_minor=1999 vs 'INR 19.99' cannot be checked", "'100' inside 'SKU-100' counted as qty"."""

    def test_confirmation_is_recognised_by_configured_patterns_not_only_a_question_mark(self):
        for steps in (["close T-1", "yes"], ["pay 1999 SKU-100", "yes"], ["reserve 8 SKU-100", "yes"]):
            self.assertEqual(run(self.p, steps)[1], [], steps)

    def test_with_the_default_question_mark_rule_the_same_flow_is_flagged(self):
        d = clone(self.tmp, {"rules.json": lambda r: {k: v for k, v in r.items() if k != "confirmation"}}, "qmark")
        res, codes = run(Project(d), ["close T-1", "yes"])
        self.assertEqual(codes, ["unconfirmed_action:close_ticket"])
        self.assertIn("looked for a question", res["findings"][0]["detail"])

    def test_patterns_can_be_set_per_action(self):
        def edit(r):
            r.pop("confirmation")
            r["actions"]["pay"]["question_patterns"] = ["^Pay INR"]
            return r
        p = Project(clone(self.tmp, {"rules.json": edit}, "peract"))
        self.assertEqual(run(p, ["pay 1999 SKU-100", "yes"])[1], [])
        self.assertEqual(run(p, ["reserve 8 SKU-100", "yes"])[1], ["unconfirmed_action:reserve"])

    def test_requirement_is_per_action_tool_plus_argument_condition(self):
        # reopen uses the same tool and needs no yes; closing does
        self.assertEqual(run(self.p, ["reopen T-2"])[1], [])
        res, codes = run(self.p, ["close T-1", "no", "yes"], T("NoCancel"))
        self.assertEqual(codes, ["unconfirmed_action:close_ticket"])
        f = res["findings"][0]
        self.assertEqual((f["tool"], f["action"]), ("update_ticket", "close_ticket"))
        self.assertIn('the user had also said "no", which reads as a no', f["detail"])
        calls = [e for e in res["events"] if e["type"] == "tool_call" and e["name"] == "update_ticket"]
        self.assertEqual(len(calls), 1)

    def test_false_claims_are_per_action_too(self):
        # a successful reopen (same tool) does not make "has been closed" true
        res, codes = run(self.p, ["reopen T-2", "say:Done, T-2 has been closed."])
        self.assertEqual(codes, ["false_claim:close_ticket"])
        self.assertEqual(run(self.p, ["close T-1", "yes"])[1], [])

    def test_an_action_must_name_a_real_tool(self):
        def edit(r):
            r["actions"]["close_ticket"].pop("tool")
            return r
        with self.assertRaises(SpecError) as cm:
            Project(clone(self.tmp, {"rules.json": edit}, "notool"))
        self.assertIn("'close_ticket' is not a tool", str(cm.exception))
        self.assertIn('"tool"', str(cm.exception))

    def test_amount_in_minor_units_is_compared_as_it_is_written(self):
        self.assertEqual(minor_forms(1999), ["19.99"])
        self.assertEqual(minor_forms(250000), ["2,500", "2,500.00", "2500", "2500.00"])
        self.assertEqual(run(self.p, ["pay 1999 SKU-100", "yes"])[1], [])
        self.assertEqual(run(self.p, ["pay 123456 SKU-200", "yes"])[1], ["rule:big_payment"])
        res, codes = run(self.p, ["pay 1999 SKU-100", "yes"], T("Overcharge"))
        self.assertEqual(codes, ["confirm_mismatch:pay"])
        self.assertIn("amount_minor=19990", res["findings"][0]["detail"])
        self.assertIn('expected to read "199.90"', res["findings"][0]["detail"])

    def test_a_number_inside_another_token_is_not_a_mention(self):
        # asked "Reserve 8 x SKU-100", reserved 100: 1.0 accepted the 100 of SKU-100 as the quantity
        res, codes = run(self.p, ["reserve 8 SKU-100", "yes"], T("WrongQty"))
        self.assertIn("confirm_mismatch:reserve", codes)
        for text, value, want in (
                ("reserve 8 x sku-100.", "100", False), ("reserve 100 x sku-100.", "100", True),
                ("order ord-100-a", "100", False), ("total 1,100 units", "100", False), ("pay 100.50", "100", False),
                ("pay inr 19.99.", "19.99", True), ("pay inr 119.99", "19.99", False), ("room 2100", "100", False),
                ("qty: 100", "100", True), ("(100)", "100", True), ("$100", "100", True), ("close t-11", "t-1", False),
                ("close t-1.", "t-1", True), ("close x-t-1", "t-1", False), ("100", "100", True), ("at 14:00", "14", True)):
            self.assertEqual(mentions(text, value), want, (text, value))

    def test_format_expression_and_value_inside_an_object_argument(self):
        def edit(r):
            r["actions"]["close_ticket"]["must_mention"] = [
                {"ticket_id": "'ticket ' + pre['ticket_id']['title'].lower()"}, {"arg": "fields.status"}]
            return r
        p = Project(clone(self.tmp, {"rules.json": edit}, "fmt"))
        res, codes = run(p, ["close T-1", "yes"])
        self.assertEqual(codes, ["confirm_mismatch:close_ticket"])
        details = sorted(f["detail"] for f in res["findings"])
        self.assertIn("fields.status='closed'", details[0])
        self.assertIn('expected to read "ticket printer on fire"', details[1])

    def test_expected_arguments_match_inside_objects(self):
        # 1.0 compared object arguments exactly, so an extra key (closed_date) failed 26 of one tester's cases
        self.assertTrue(match_args({"fields": {"status": "closed"}}, {"fields": {"status": "closed", "closed_date": "x"}}))
        self.assertFalse(match_args({"fields": {"status": "open"}}, {"fields": {"status": "closed"}}))
        self.assertFalse(match_args({"fields": {"status": "closed"}}, {"fields": "closed"}))
        self.assertEqual(run(self.p, ["close T-1", "yes"], expect={
            "calls": [{"tool": "update_ticket", "args": {"ticket_id": "T-1", "fields": {"status": "closed"}}, "count": 1}],
            "no_calls": [{"tool": "update_ticket", "args": {"fields": {"status": "open"}}}]})[1], [])

    def test_simulated_users_recognise_the_configured_confirmation_wording(self):
        d = clone(self.tmp, {"population.json": lambda _: {"goals": {"g": {"open": ["close T-1"]}}}}, "cue")
        table = population.cue_table(Project(d))
        self.assertEqual(population.perceive(table, "Close T-1." + ASK), "confirm")


# ============================================================================== 3. shrinking
class TestShrinking(ShopCase):
    """Feedback (6 testers): "'transfer..., no, transfer 200, yes' was shrunk to 'transfer 500, yes',
    which is correct behaviour"; "the advance step was dropped"; "--export saved it as a regression
    case that will fail forever on a correct product"; "expect:calls is not shrunk at all"."""

    def failing(self, steps, target, expect, cid="s"):
        res = execute(self.p, target, cases=[case(steps, cid, expect=expect)])
        c = replay.case_from_log(self.p, res["events"], cid)
        return c, {(f["code"], f.get("expect_key")) for f in res["findings"]}

    def says(self, c):
        return [s.get("say", "<" + next(iter(s)) + ">") for s in c["steps"]]

    def test_the_no_is_never_shrunk_away(self):
        c, found = self.failing(["hello", "close T-1", "no", "yes", "time"], T("NoCancel"),
                                {"no_calls": ["pay", "update_ticket"], "unchanged": ["tickets"]})
        self.assertIn(("expect:no_calls", "no_calls[1]"), found)
        info = {}
        short, _ = replay.shrink(self.p, T("NoCancel"), c, "expect:no_calls", key="no_calls[1]", info=info)
        self.assertEqual(self.says(short), ["close T-1", "no", "yes"])
        self.assertEqual(info["mode"], "trim")
        self.assertIn("the user says no here", info["kept"].values())
        # the script 1.0 produced ("close T-1", "yes") is the correct happy path: it must not be reachable
        self.assertEqual(replay.shrink_mode("expect:no_calls"), "trim")
        short2, _ = replay.shrink(self.p, T("NoCancel"), c, "expect:unchanged", key="unchanged[0]")
        self.assertEqual(self.says(short2), ["close T-1", "no", "yes"])

    def test_clock_jump_and_setup_are_kept(self):
        steps = ["time", {"advance": {"hours": 10}}, "reserve 8 SKU-100", "yes", "hello"]
        setup = [{"entity": "stock", "id": "SKU-100", "set": {"qty": 9}}]
        res = execute(self.p, T("StaleClock"), cases=[case(steps, "late", expect={"no_calls": ["reserve"]}, setup=setup)])
        self.assertEqual([f["code"] for f in res["findings"]], ["expect:no_calls"])
        c = replay.case_from_log(self.p, res["events"], "late")
        short, info = replay.validated_shrink(self.p, T("StaleClock"), c, "expect:no_calls", "no_calls[0]")
        self.assertEqual(self.says(short), ["time", "<advance>", "reserve 8 SKU-100", "yes"])
        self.assertEqual(short["setup"], setup)
        self.assertTrue(info["validated"])
        self.assertEqual(info["replay_hits"], 3)

    def test_other_window_is_kept(self):
        steps = [{"session": "a", "say": "close T-1"}, {"session": "a", "say": "no"},
                 {"session": "b", "say": "hello"}, {"session": "a", "say": "yes"}]
        c, _ = self.failing(steps, T("NoCancel"), {"no_calls": ["update_ticket"]})
        short, _ = replay.shrink(self.p, T("NoCancel"), c, "expect:no_calls", key="no_calls[0]")
        self.assertEqual(self.says(short), ["close T-1", "no", "hello", "yes"])

    def test_a_shrunk_script_must_fail_on_the_same_expectation_entry(self):
        c, _ = self.failing(["close T-1", "no", "yes"], T("NoCancel"), {"no_calls": ["pay", "update_ticket"]})
        self.assertEqual(replay.fires(self.p, T("NoCancel"), c, "expect:no_calls", key="no_calls[1]")[0], 1)
        self.assertEqual(replay.fires(self.p, T("NoCancel"), c, "expect:no_calls", key="no_calls[0]")[0], 0)

    def test_export_keeps_only_the_expectation_that_failed_and_replays_it_first(self):
        c, _ = self.failing(["hello", "close T-1", "no", "yes"], T("NoCancel"),
                            {"no_calls": ["pay", "update_ticket"], "unchanged": ["tickets"],
                             "reply_contains": ["never said"]})
        short, info = replay.validated_shrink(self.p, T("NoCancel"), c, "expect:no_calls", "no_calls[1]")
        out = os.path.join(self.tmp, "exp1")
        path = replay.export_case(self.p, short, "expect:no_calls", "d", out, key="no_calls[1]", target=T("NoCancel"))
        saved = load(path)
        self.assertEqual(saved["expect"], {"no_calls": ["update_ticket"]})
        self.assertEqual([s["say"] for s in saved["steps"]], ["close T-1", "no", "yes"])
        self.assertIn("failed 3 of 3 replays", saved["origin"]["validated"])
        loaded = self.p.load_cases([path])
        self.assertIn("expect:no_calls", [f["code"] for f in execute(self.p, T("NoCancel"), cases=loaded)["findings"]])
        self.assertEqual(execute(self.p, T("Shop"), cases=loaded)["findings"], [], "passes on a correct product")

    def test_export_refuses_a_script_that_passes(self):
        # exactly the 1.0 accident: a script on which the product behaves correctly
        good = case(["close T-1", "no", "yes"], "fine", expect={"no_calls": ["update_ticket"]})
        out = os.path.join(self.tmp, "exp2")
        with self.assertRaises(replay.ExportRefused) as cm:
            replay.export_case(self.p, good, "expect:no_calls", "", out, key="no_calls[0]", target=T("Shop"))
        self.assertIn("not exported", str(cm.exception))
        self.assertIn("passes on the expectation no_calls[0]", str(cm.exception))
        self.assertFalse(os.path.exists(out), "nothing is written")
        with self.assertRaises(replay.ExportRefused):
            replay.export_case(self.p, case(["hello"], "h"), "privacy_leak:users.account", "", out)

    def test_did_not_happen_failures_are_shrunk_without_losing_the_cause(self):
        steps = ["hello", "reserve 8 SKU-100", "time", "yes", "hello", "show T-1"]
        exp = {"calls": [{"tool": "reserve", "args": {"sku": "SKU-100", "qty": 8}, "count": 1}]}
        c, found = self.failing(steps, T("Forgets"), exp)
        self.assertEqual(found, {("expect:calls", "calls[0]")})
        self.assertEqual(replay.shrink_mode("expect:calls", "calls[0]"), "inert")
        short, info = replay.validated_shrink(self.p, T("Forgets"), c, "expect:calls", "calls[0]")
        # "time" is the message that made the product forget: it stays. So does "show T-1": a program
        # cannot know that it is beside the point. Only the greetings go.
        self.assertEqual(self.says(short), ["reserve 8 SKU-100", "time", "yes", "show T-1"])
        self.assertIn("it says something (not a greeting, thanks or junk)", info["kept"].values())
        self.assertTrue(info["validated"])
        self.assertEqual(execute(self.p, T("Shop"), cases=[short])["findings"], [], "still a fair script")

    def test_did_not_happen_never_drops_the_yes_or_the_request(self):
        # a deaf product ignores the yes; removing an ignored message changes nothing else, so a naive
        # "nothing else changed" rule would cut it and leave a script that fails on any product
        exp = {"calls": ["reserve"], "world": [{"entity": "stock", "id": "SKU-100", "field": "qty", "equals": 32}]}
        c, _ = self.failing(["reserve 8 SKU-100", "yes", "hello", "thanks"], T("Deaf"), exp)
        for code, key in (("expect:calls", "calls[0]"), ("expect:world", "world[0]")):
            short, _ = replay.shrink(self.p, T("Deaf"), c, code, key=key)
            self.assertEqual(self.says(short), ["reserve 8 SKU-100", "yes"], code)
            self.assertEqual(execute(self.p, T("Shop"), cases=[short])["findings"], [])
        # nor a message the buggy product happens to ignore: it may be the very thing it should not ignore
        c, _ = self.failing(["hello", "reserve 8 SKU-100", "who U2", "yes"], T("Deaf"), exp)
        short, _ = replay.shrink(self.p, T("Deaf"), c, "expect:calls", key="calls[0]")
        self.assertEqual(self.says(short), ["reserve 8 SKU-100", "who U2", "yes"])

    def test_must_not_happen_keeps_every_message_that_says_something(self):
        # "time" before the request is not a no, a yes or a clock jump, and the product behaves the
        # same without it; it stays all the same, because it may be what makes the action wrong
        c, _ = self.failing(["hello", "time", "close T-1", "no", "yes", "thanks"], T("NoCancel"),
                            {"no_calls": ["update_ticket"]})
        short, _ = replay.shrink(self.p, T("NoCancel"), c, "expect:no_calls", key="no_calls[0]")
        self.assertEqual(self.says(short), ["time", "close T-1", "no", "yes"])
        self.assertEqual(replay.filler_messages(self.p) & {"hello", "hi", "thanks", "close t 1"}, {"hello", "hi", "thanks"})

    def test_checks_that_carry_their_own_evidence_are_still_shrunk_fully(self):
        res = execute(self.p, T("NoCancel"), cases=[case(["hello", "time", "close T-1", "no", "hello", "yes", "time"], "u")])
        c = replay.case_from_log(self.p, res["events"], "u")
        short, info = replay.validated_shrink(self.p, T("NoCancel"), c, "unconfirmed_action:close_ticket")
        self.assertEqual(info["mode"], "full")
        self.assertEqual(self.says(short), ["close T-1", "no", "yes"])

    def test_report_and_cli_say_how_a_script_was_cut_and_refuse_bad_exports(self):
        d = clone(self.tmp, name="cli")
        with open(os.path.join(d, "cases", "c.json"), "w") as f:
            json.dump([{"id": "no-then-yes", "user": "U1", "steps": ["hello", "close T-1", "no", "yes", "time"],
                        "expect": {"no_calls": ["update_ticket"]}},
                       {"id": "forgot", "user": "U1", "steps": ["reserve 8 SKU-100", "yes", "hello"],
                        "expect": {"calls": ["reserve"]}}], f)
        rc, out = sh("run", "--target", T("Deaf"), "--name", "deaf", "--only", "forgot", "--export", cwd=d)
        self.assertEqual(rc, 1, out)
        rep = load(os.path.join(d, "runs", "deaf", "report.json"))
        ex = rep["problems"][0]["example"]
        self.assertEqual((ex["shrink_mode"], ex["short_messages"], ex["original_messages"]), ("inert", 2, 3))
        self.assertIn("did not happen", read(os.path.join(d, "runs", "deaf", "report.md")))
        self.assertEqual(load(ex["saved_as"])["expect"], {"calls": ["reserve"]})
        rc, out = sh("run", "--target", T("NoCancel"), "--name", "nc", "--only", "no-then-yes", "--replays", "0", cwd=d)
        rc, out = sh("replay", "nc", "no-then-yes", "--code", "expect:no_calls", "-n", "2", "--shrink", "--export",
                     "--target", T("NoCancel"), cwd=d)
        self.assertIn("happened in 2 of 2 replays", out)
        self.assertIn("shrunk from 5 to 3 user messages", out)
        self.assertIn("must not happen", out)
        self.assertIn("User: no", out)
        self.assertIn("saved: ", out)
        # replaying against the correct product: nothing to export, and it says so
        rc, out = sh("replay", "nc", "no-then-yes", "--code", "expect:no_calls", "-n", "2", "--export", cwd=d)
        self.assertIn("happened in 0 of 2 replays", out)
        self.assertNotIn("saved: ", out)


# ============================================================================== 4. reports
class TestRootCauseReport(ShopCase):
    """Feedback (9 testers): "208 findings for 8 bugs", "one root cause shows up under 5-6 codes",
    "every rules.py failure is titled 'A rule of the product was broken'"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        no = {"no_calls": [{"tool": "update_ticket", "args": {"fields": {"status": "closed"}}}], "unchanged": ["tickets"]}
        cls.cases = [
            case(["close T-1", "no", "yes"], "no-yes-1", expect=no),
            case(["hello", "close T-2", "cancel", "yes"], "no-yes-2", expect=no),
            case(["close T-1", "stop", "yes", "time"], "no-yes-3", expect=dict(no, last_reply_contains=["Cancelled"])),
            case([{"session": "a", "say": "close T-1"}, {"session": "a", "say": "no"},
                  {"session": "b", "say": "hello"}, {"session": "a", "say": "yes"}], "no-yes-window", expect=no),
            case(["reserve 8 SKU-100", "yes"], "qty-1", expect={"calls": [{"tool": "reserve", "args": {"qty": 8}}]}),
            case(["reserve 5 SKU-200", "yes"], "qty-2", user="S1", expect={"calls": [{"tool": "reserve", "args": {"qty": 5}}]}),
            case(["say:THIS IS VERY LOUD"], "loud"),
            case(["pay 123456 SKU-100", "yes"], "big"),
            case(["hello"], "fine"),
        ]
        cls.res = execute(cls.p, T("Buggy"), cases=cls.cases)
        cls.probs = report.triage(cls.p, T("Buggy"), cls.res["events"], cls.res["findings"], replays=2)
        cls.rep = report.build(cls.p, "r", cls.res["events"], cls.res["findings"], cls.res["warnings"], cls.probs)
        cls.md = report.markdown(cls.rep)

    def prob(self, code, trigger=None):
        return next(p for p in self.probs if p["code"] == code and (trigger is None or p["trigger"] == trigger))

    def test_findings_of_one_root_cause_are_one_problem(self):
        self.assertGreaterEqual(len(self.res["findings"]), 16)
        self.assertEqual(len(self.probs), 5, [(p["code"], p["trigger"], p["count"]) for p in self.probs])
        p = self.prob("unconfirmed_action:close_ticket", ["no", "yes"])
        self.assertEqual(p["conversations"], ["no-yes-1", "no-yes-2", "no-yes-3"])
        self.assertEqual(p["codes"], {"unconfirmed_action:close_ticket": 3, "expect:no_calls": 3,
                                      "expect:unchanged": 3, "expect:last_reply_contains": 1})
        self.assertEqual((p["tool"], p["action"]), ("update_ticket", "close_ticket"))
        self.assertEqual(p["trigger_text"], "no → yes")

    def test_same_check_with_different_trigger_steps_is_a_different_problem(self):
        p = self.prob("unconfirmed_action:close_ticket", ["no", "another window", "yes"])
        self.assertEqual(p["conversations"], ["no-yes-window"])

    def test_several_checks_on_the_same_action_are_merged_with_counts(self):
        p = self.prob("confirm_mismatch:reserve")
        self.assertEqual(p["count"], 2)
        self.assertEqual(p["codes"], {"confirm_mismatch:reserve": 2, "rule:reserve-limit": 2, "expect:calls": 2})

    def test_all_distinct_examples_are_listed_by_first_line(self):
        p = self.prob("unconfirmed_action:close_ticket", ["no", "yes"])
        lines = [(e["conversation"], e["code"]) for e in p["examples"]]
        self.assertEqual(len(lines), len(set((e["code"], e["detail"]) for e in p["examples"])))
        self.assertIn(("no-yes-2", "unconfirmed_action:close_ticket"), lines, "T-2 reads differently from T-1")
        self.assertIn(("no-yes-3", "expect:last_reply_contains"), lines)
        self.assertIn("**All distinct examples**", self.md)
        self.assertIn("- `no-yes-2` [unconfirmed_action:close_ticket] closing a ticket was done (ticket_id=T-2", self.md)

    def test_every_custom_rule_has_its_own_headline(self):
        self.assertEqual(self.prob("rule:no-shouting")["title"], "The assistant shouted at the user")   # RULES in rules.py
        self.assertEqual(self.prob("rule:no-shouting")["why"], "House style: never all capitals.")
        self.assertEqual(self.prob("rule:big_payment")["title"], "Rule broken: Big payment")           # from the id
        self.assertNotIn("A rule of the product was broken", self.md)
        self.assertEqual(report.explain(self.p, "rule:reserve-limit", {"title": "More than 50 units were reserved at once"})[0],
                         "More than 50 units were reserved at once")                                   # ctx.fail(title=)
        self.assertEqual(report.explain(self.p, "rule:closed-stays-closed-on-reopen-by-other")[0],
                         "A ticket was changed by someone who does not own it")                        # rules.json title
        self.assertEqual(report.explain(self.p, "rule:greeting-first")[0], "A session did not start with a greeting")

    def test_markdown_and_json_carry_the_grouping(self):
        self.assertIn("**5 problem(s) found**", self.md)
        self.assertIn("| # | Problem | Action | Steps leading to it | Conversations | Happens again on replay | Also seen as |", self.md)
        self.assertIn("| close_ticket | no → yes | 3 | 2 of 2 | expect:last_reply_contains (1), expect:no_calls (3), "
                      "expect:unchanged (3) |", self.md)
        self.assertIn("**Seen by.**", self.md)
        self.assertIn("**Common to all of them.** action `close_ticket` (tool `update_ticket`); steps leading to it: no → yes.", self.md)
        self.assertEqual(self.rep["by_conversation"]["no-yes-1"]["codes"],
                         ["unconfirmed_action:close_ticket", "expect:no_calls", "expect:unchanged"])
        self.assertEqual(len(self.rep["by_conversation"]["no-yes-1"]["problems"]), 1)
        self.assertNotIn("fine", self.rep["by_conversation"])
        self.assertEqual(self.rep["summary"]["findings"], len(self.res["findings"]))
        json.dumps(self.rep)

    def test_console_summary_names_the_rule_and_the_grouping(self):
        d = clone(self.tmp, name="console")
        with open(os.path.join(d, "cases", "c.json"), "w") as f:
            json.dump([{k: v for k, v in c.items()} for c in self.cases], f)
        rc, out = sh("run", "--target", T("Buggy"), "--replays", "1", "--no-shrink", cwd=d)
        self.assertEqual(rc, 1, out)
        self.assertIn("[rule:no-shouting] The assistant shouted at the user: 1 conversation(s)", out)
        self.assertIn("after no → yes", out)
        self.assertIn("also seen as expect:no_calls, expect:unchanged", out)
        self.assertRegex(out, r"\d+ finding\(s\) -> 5 problem\(s\) by root cause")
        rc, out = sh("show", cwd=d)
        self.assertIn("FAIL  no-yes-1   <- ", out)
        self.assertIn("ok    fine", out)
        self.assertIn("(8 of 9 conversations have findings)", out)


# ============================================================================== 5. setup and docs
class TestInitAndValidate(unittest.TestCase):
    """Feedback (6 testers): "validate crashed with KeyError: 'tasks'" after replacing the template world."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_template_leftovers_give_clear_errors_not_a_traceback(self):
        d = os.path.join(self.tmp, "proj")
        rc, out = sh("init", d)
        self.assertEqual(rc, 0, out)
        self.assertIn("population.json   <- sample simulated-user goals", out)
        self.assertIn("--bare", out)
        for f in ("world.json", "tools.json", "tools.py", "rules.py"):
            shutil.copy(os.path.join(SHOP, f), os.path.join(d, f))
        # 1. rules.json still names the sample tools
        rc, out = sh("validate", "--no-target", cwd=d)
        self.assertEqual(rc, 2, out)
        self.assertNotIn("Traceback", out)
        self.assertIn("'delete_task' is not a tool in tools.json", out)
        self.assertIn("left over from the init template", out)
        shutil.copy(os.path.join(SHOP, "rules.json"), os.path.join(d, "rules.json"))
        # 2. population.json and cases/starter.json still name the sample entity and users
        rc, out = sh("validate", "--no-target", cwd=d)
        self.assertEqual(rc, 1, out)
        self.assertNotIn("Traceback", out)
        self.assertNotIn("KeyError", out)
        self.assertIn("PROBLEM: population.json: goal 'delete_task' picks from entity 'tasks', which is not in world.json", out)
        self.assertIn("unknown user 'alice'", out)
        self.assertIn("names unknown tool 'delete_task'", out)

    def test_bare_init_validates_as_it_is(self):
        d = os.path.join(self.tmp, "bare")
        rc, out = sh("init", d, "--bare")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(os.path.join(d, "population.json")))
        self.assertFalse(os.path.exists(os.path.join(d, "target")))
        rc, out = sh("validate", "--no-target", cwd=d)
        self.assertEqual(rc, 0, out)
        self.assertIn("OK", out)
        rc, out = sh("validate", cwd=d)
        self.assertEqual(rc, 1)
        self.assertIn("PROBLEM: target: poptest.json has no 'target'", out)

    def test_validate_never_shows_a_traceback(self):
        breakers = {
            "tools.py syntax": ("tools.py", "def broken(:\n"),
            "tools.py import": ("tools.py", "import no_such_module_xyz\n"),
            "rules.py crash": ("rules.py", "raise RuntimeError('boom at import')\n"),
            "tools.json list": ("tools.json", "[1, 2]"),
            "tools.json tool string": ("tools.json", '{"tools": {"now": "x"}}'),
            "rules.json actions list": ("rules.json", '{"actions": ["pay"]}'),
            "rules.json invariant string": ("rules.json", '{"invariants": ["x", {"id": "a", "on": "reply", "match": "(", "require": "1 +"}]}'),
            "rules.json bad pattern": ("rules.json", '{"confirmation": {"question_patterns": ["("]}, "actions": {"pay": {"needs_confirmation": true}}}'),
            "world.json no entities": ("world.json", '{"entities": {}}'),
            "world.json bad generator": ("world.json", '{"entities": {"users": {"generate": {"count": "x", "fields": {"id": {"wat": 1}}}}}}'),
            "world.json bad clock": ("world.json", '{"clock": {"start_hour": 31}, "entities": {"users": {"records": [{"id": "U1"}]}}}'),
            "world.json records string": ("world.json", '{"entities": {"users": {"records": "nope"}}}'),
            "population goals list": ("population.json", '{"goals": ["a"]}'),
            "population goal string": ("population.json", '{"goals": {"g": "x"}}'),
            "population bad where": ("population.json", '{"goals": {"g": {"open": ["hi"], "pick": {"entity": "tickets", "where": "rec[\'nope\'] > user"}}}}'),
            "population bad owner": ("population.json", '{"goals": {"g": {"open": ["hi"], "pick": {"entity": "stock", "owner": "them"}}}}'),
            "cases expect string": ("cases/x.json", '[{"id": "a", "user": "U1", "steps": ["hi"], "expect": "calls"}]'),
            "cases steps number": ("cases/x.json", '[{"id": "a", "user": "U1", "steps": [3]}]'),
            "cases not json": ("cases/x.json", '[{"id": '),
            "cases unknown expect": ("cases/x.json", '[{"id": "a", "user": "U1", "steps": ["hi"], "expect": {"last_reply_has": ["x"], "calls": "now"}}]'),
            "cases setup junk": ("cases/x.json", '[{"id": "a", "user": "U1", "steps": ["hi"], "setup": ["x"]}]'),
            "poptest.json noise": ("poptest.json", '{"target": {"adapter": "python", "entry": "bot.py:Shop"}, "noise": {"replies": ["("]}}'),
            "poptest.json target junk": ("poptest.json", '{"target": {"adapter": "python", "entry": "bot.py:Missing"}}'),
            "poptest.json not object": ("poptest.json", '[]'),
        }
        for name, (fname, text) in breakers.items():
            d = clone(self.tmp, name="b-" + name.replace(" ", "-").replace(".", "-"))
            with open(os.path.join(d, fname), "w") as f:
                f.write(text)
            for args in (("validate",), ("run", "--replays", "0"), ("say", "--user", "U1", "hello"), ("personas",)):
                rc, out = sh(*args, cwd=d)
                self.assertNotIn("Traceback", out, f"{name}: {args}\n{out}")
                if args == ("validate",):
                    self.assertIn(rc, (1, 2), f"{name}\n{out}")
                    self.assertTrue("PROBLEM: " in out or "poptest: " in out, f"{name}\n{out}")

    def test_specific_messages(self):
        d = clone(self.tmp, {"population.json": lambda _: {"goals": {}}}, "msgs")
        rc, out = sh("validate", cwd=d)
        self.assertEqual(rc, 0, out)   # 1.0: "PROBLEM" although population mode is optional
        self.assertIn("note: population.json has no goals: population mode (optional) is not set up", out)
        with open(os.path.join(d, "cases", "x.json"), "w") as f:
            json.dump([{"id": "a", "user": "U1", "steps": ["hi", {"session": "main", "user": "U2", "say": "x"}],
                        "expect": {"last_reply_has": ["x"], "last_reply_not_contains": ["y"]}}], f)
        rc, out = sh("validate", cwd=d)
        self.assertEqual(rc, 1)
        self.assertIn("unknown expectation 'last_reply_has'. Known: calls, no_calls, world, unchanged", out)
        self.assertIn("session 'main' already belongs to U1; a later step cannot switch it to U2", out)
        self.assertNotIn("last_reply_not_contains'", out)

    def test_unknown_user_cases_are_allowed_when_declared(self):
        d = clone(self.tmp, name="ghost")
        cases = [{"id": "ghost", "user": "mallory", "steps": ["who mallory"],
                  "expect": {"reply_contains": ["error 404: unknown user"], "no_calls": ["pay"]}}]
        with open(os.path.join(d, "cases", "g.json"), "w") as f:
            json.dump(cases, f)
        rc, out = sh("validate", cwd=d)
        self.assertEqual(rc, 1)
        self.assertIn("unknown user 'mallory'", out)
        self.assertIn('"unknown_user": true', out)
        cases[0]["unknown_user"] = True
        with open(os.path.join(d, "cases", "g.json"), "w") as f:
            json.dump(cases, f)
        rc, out = sh("validate", cwd=d)
        self.assertEqual(rc, 0, out)
        rc, out = sh("run", cwd=d)
        self.assertEqual(rc, 0, out)
        # or project-wide
        cases[0].pop("unknown_user")
        with open(os.path.join(d, "cases", "g.json"), "w") as f:
            json.dump(cases, f)
        cfg = load(os.path.join(d, "poptest.json"))
        cfg["unknown_users"] = ["mallory"]
        with open(os.path.join(d, "poptest.json"), "w") as f:
            json.dump(cfg, f)
        self.assertEqual(sh("validate", cwd=d)[0], 0)

    def test_internal_errors_are_one_clear_line(self):
        d = clone(self.tmp, name="internal")
        with open(os.path.join(d, "world.json"), "w") as f:
            f.write('{"entities": {"users": {"records": [{"id": "U1"}], "generate": {"count": 2, "fields": {"id": {"template": "{missing}"}}}}}}')
        rc, out = sh("world", cwd=d)
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", out)
        self.assertIn("poptest: world failed: KeyError", out)
        self.assertIn("POPTEST_DEBUG=1", out)
        rc, out = sh("world", cwd=d, env={"POPTEST_DEBUG": "1"})
        self.assertIn("Traceback", out)


class TestClock(ShopCase):
    """Feedback (6 testers): "world.now() starts at 09:00 and world.date()/world.day roll over every
    1440 minutes from run start, i.e. at 09:00, not at midnight"; "no way to set the start hour"."""

    def world(self, **clock):
        spec = json.loads(json.dumps(self.p.world_spec))
        spec["clock"].update(clock)
        return World(spec, 1)

    def test_day_date_and_now_roll_together_at_midnight(self):
        w = self.world()
        self.assertEqual((w.day, w.date(), w.now(), w.hour(), w.time()), (100, "2026-03-02", "2026-03-02T09:00", 9, "09:00"))
        w.advance(hours=14, minutes=59)
        self.assertEqual((w.day, w.date(), w.now()), (100, "2026-03-02", "2026-03-02T23:59"))
        w.advance(minutes=1)
        self.assertEqual((w.day, w.date(), w.now(), w.hour()), (101, "2026-03-03", "2026-03-03T00:00", 0))
        for _ in range(200):
            w.advance(hours=7, minutes=13)
            self.assertEqual(w.now()[:10], w.date())
            self.assertEqual(int(w.now()[11:13]), w.hour())
            self.assertEqual(w.days_since("2026-03-02"), w.day - 100)

    def test_start_hour_is_settable(self):
        self.assertEqual(self.world(start_hour=22).now(), "2026-03-02T22:00")
        self.assertEqual(self.world(start_hour=0).now(), "2026-03-02T00:00")
        self.assertEqual(self.world(start_time="07:45").time(), "07:45")
        w = self.world(start_hour=22)
        w.advance(hours=3)
        self.assertEqual((w.day, w.hour()), (101, 1))
        for bad in ({"start_hour": 24}, {"start_time": "9am"}, {"start_hour": "x"}, {"start_date": "tomorrow"}):
            with self.assertRaises(SpecError, msg=bad):
                self.world(**bad)

    def test_set_time_weekday_and_clock_endpoint(self):
        w = self.world()
        w.set_time(17, 30)
        self.assertEqual((w.day, w.time(), w.weekday()), (100, "17:30", 0))
        w.set_time(8)
        self.assertEqual((w.day, w.time()), (100, "08:00"))
        box = ToolBox(w, self.p.tools_spec, self.p.handlers, lambda ev: None)
        srv = ToolServer(box)
        try:
            with urllib.request.urlopen(srv.url + "/clock", timeout=5) as r:
                self.assertEqual(json.load(r), {"day": 100, "date": "2026-03-02", "now": "2026-03-02T08:00", "hour": 8,
                                                "minute": 0, "time": "08:00", "weekday": 0})
        finally:
            srv.close()

    def test_a_case_can_start_at_a_time_of_day_and_jump_hours(self):
        res, codes = run(self.p, ["time", "reserve 8 SKU-100", {"advance": {"hours": 2}}, "time"], clock={"hour": 17},
                         expect={"reply_contains": ["It is 2026-03-02T17:00 (day 100, hour 17)", "Reserve 8 x SKU-100",
                                                    "It is 2026-03-02T19:00"]})
        self.assertEqual(codes, [])
        res, codes = run(self.p, ["time"], clock={"hour": 23, "minute": 30, "days": 1},
                         expect={"last_reply_contains": ["2026-03-03T23:30 (day 101, hour 23)"]})
        self.assertEqual(codes, [])
        # the checker sees the same clock as the fake tools did
        ev = [e for e in res["events"] if e["type"] == "tool_call"][0]
        self.assertEqual((ev["day"], ev["result"]["day"]), (101, 101))

    def test_say_accepts_clock_jumps_between_messages(self):
        rc, out = sh("say", "--user", "U1", "--hour", "8", "time", "+13h", "time", "+2d", "time", cwd=SHOP)
        self.assertEqual(rc, 0, out)
        self.assertIn("It is 2026-03-02T08:00", out)
        self.assertIn("--- time passes: 13 hours", out)
        self.assertIn("It is 2026-03-02T21:00", out)
        self.assertIn("It is 2026-03-04T21:00 (day 102, hour 21)", out)

    def test_dates_are_usable_in_rule_expressions(self):
        ns = {"today": "2026-03-02"}
        self.assertTrue(safe_eval("date.fromisoformat('2026-03-16') <= date.fromisoformat(today) + timedelta(days=14)", ns))
        self.assertEqual(safe_eval("days_between(today, '2026-03-30T10:00')", ns), 28)
        self.assertEqual(safe_eval("datetime.fromisoformat('2026-03-02T09:00').hour", {}), 9)


class TestToolErrorsAndResults(ShopCase):
    """Feedback (5 testers): "how a fake tool returns an API error is not documented; HTTP status
    is always 400"; "{'ok': false} from verify_identity counts as a failed call"."""

    def box(self, **ctx):
        w = self.p.new_world()
        ev = []
        b = ToolBox(w, self.p.tools_spec, self.p.handlers, ev.append)
        b.context = dict({"user": "U1"}, **ctx)
        return b, w, ev

    def test_tool_error_carries_a_status_in_process(self):
        b, w, ev = self.box()
        with self.assertRaises(ToolError) as cm:
            b.get_user(user_id="ghost")
        self.assertEqual((str(cm.exception), cm.exception.status), ("unknown user", 404))
        self.assertEqual((ev[-1]["error"], ev[-1]["status"]), ("unknown user", 404))
        self.assertEqual(ToolError("x").status, 400)
        with self.assertRaises(ToolError) as cm:
            b.nope()
        self.assertEqual(cm.exception.status, 404)

    def test_status_codes_over_http(self):
        b, w, ev = self.box()
        srv = ToolServer(b)

        def post(path, body):
            req = urllib.request.Request(srv.url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)
        try:
            self.assertEqual(post("/call/get_user", {"user_id": "ghost"}), (404, {"error": "unknown user"}))
            self.assertEqual(post("/call/get_user", {}), (400, {"error": "get_user: missing argument(s) ['user_id']"}))
            self.assertEqual(post("/call/get_user", {"user_id": "U1"}), (200, {"result": {"id": "U1", "name": "Uma"}}))
            self.assertEqual(post("/call/update_ticket", {"ticket_id": "T-1", "fields": 5})[0], 500)   # handler crash
            self.assertEqual(post("/call/nope", {})[0], 404)
        finally:
            srv.close()

    def test_a_negative_answer_is_not_a_failed_call_when_the_tool_says_so(self):
        self.assertFalse(call_ok({"ok": False}))
        self.assertTrue(call_ok({"ok": False}, None, {"ok_from_result": False}))
        self.assertFalse(call_ok(None, "boom", {"ok_from_result": False}))
        res, codes = run(self.p, ["verify 9999"], expect={"calls": [{"tool": "verify", "count": 1}],
                                                         "last_reply_contains": ["Wrong code"]})
        self.assertEqual(codes, [])

    def test_backend_failures_can_be_injected_from_a_case(self):
        steps = [{"fail": {"tool": "update_ticket", "error": "backend timeout", "status": 503}}, "reopen T-2", "reopen T-2"]
        res = execute(self.p, cases=[case(steps)])
        calls = [e for e in res["events"] if e["type"] == "tool_call"]
        self.assertEqual([(c.get("error"), c.get("status"), bool(c["changes"])) for c in calls],
                         [("backend timeout", 503, False), (None, None, True)])
        self.assertTrue(calls[0]["injected"])
        self.assertIn("crash", {f["code"] for f in res["findings"]})   # the shop does not catch it: that is the finding
        f = next(f for f in res["findings"] if f["code"] == "crash")
        self.assertEqual(f["trigger"], ["backend failure"])
        self.assertIn("--- test setup: the next update_ticket call fails (backend timeout)", transcript(res["events"], "t"))
        steps = [{"fail": {"tool": "*", "times": "always"}}, "who U1", "who U1", {"fail": {"clear": True}}, "who U1"]
        res = execute(self.p, cases=[case(steps)])
        self.assertEqual([e["text"] for e in res["events"] if e["type"] == "bot_msg"],
                         ["error 503: backend unavailable", "error 503: backend unavailable", "Uma"])
        with self.assertRaises(SpecError):
            execute(self.p, cases=[case([{"fail": {"tool": "no_such"}}, "hello"])])

    def test_new_ids_continue_after_the_fixtures(self):
        w = self.p.new_world()
        self.assertEqual(w.add("payments", owner="U1")["id"], "P-1002")   # 1.0 gave P-0001
        self.assertEqual(w.add("tickets", owner="U1")["id"], "T-8")


class TestRulesApi(ShopCase):
    """Feedback (7 testers): "the skill names the hook functions but not the ctx attributes";
    "rules.py hooks fail silently"; "ctx.replies mixes all sessions"."""

    def test_ctx_fields_for_each_hook(self):
        seen = {}
        hooks = self.p.rules_module
        old = {k: getattr(hooks, k, None) for k in ("on_call", "on_reply", "on_end")}
        try:
            for name in old:
                setattr(hooks, name, lambda ctx, name=name: seen.setdefault(name, ctx))
            steps = [{"session": "a", "say": "hello"}, {"session": "b", "say": "close T-1"}, {"session": "b", "say": "yes"}]
            execute(self.p, cases=[case(steps)])
        finally:
            for k, v in old.items():
                setattr(hooks, k, v) if v else delattr(hooks, k)
        c = seen["on_call"]
        self.assertEqual((c.tool, c.args, c.ok, c.error, c.status, c.user, c.session), ("now", {}, True, None, None, "U1", "t:b"))
        self.assertEqual(c.session_messages, [{"role": "user", "text": "close T-1", "seq": c.session_messages[0]["seq"]},
                                              {"role": "system", "text": "Close T-1." + ASK, "seq": c.session_messages[1]["seq"]},
                                              {"role": "user", "text": "yes", "seq": c.session_messages[2]["seq"]}])
        self.assertEqual(c.session_user_msgs, ["close T-1", "yes"])
        self.assertEqual(c.session_replies, ["Close T-1." + ASK])
        self.assertEqual((c.stance("yes please"), c.stance("don't"), c.stance("hm")), ("yes", "no", "other"))
        self.assertEqual(c.world.hour(), 9)
        r = seen["on_reply"]
        self.assertEqual((r.text, r.session, r.session_replies, r.said), ("Hello.", "t:a", ["Hello."], "\nhello"))
        e = seen["on_end"]
        self.assertTrue(hasattr(e, "changes") and hasattr(e, "calls") and e.session is None)
        for field in ("world", "user", "case_user", "day", "session", "conv_id", "event", "calls", "replies", "user_msgs",
                      "session_messages", "session_replies", "session_user_msgs", "said"):
            self.assertIn(f"ctx.{field}", sys.modules["poptest.checks"].Ctx.__doc__)

    def test_session_messages_do_not_mix_windows(self):
        steps = [{"session": "a", "say": "hello"}, {"session": "b", "say": "say:session-probe"}]
        res = execute(self.p, cases=[case(steps)])
        f = next(f for f in res["findings"] if f["code"] == "rule:probe")
        self.assertEqual(f["detail"], "user:say:session-probe | system:session-probe")

    def test_an_exception_in_a_hook_is_a_warning_not_silence_and_not_a_crash(self):
        res = execute(self.p, cases=[case(["say:explode-hook", "say:SHOUTING VERY LOUDLY"], "boom")])
        self.assertEqual(len(res["warnings"]), 1)
        w = res["warnings"][0]
        self.assertIn("rules.py on_reply raised KeyError: 'nope'", w)
        self.assertIn("rules.py line", w)
        self.assertIn("conversation boom", w)
        self.assertEqual([f["code"] for f in res["findings"]], ["rule:no-shouting"], "the other rules still ran")
        rc, out = sh("say", "--user", "U1", "say:explode-hook", cwd=SHOP)
        self.assertIn("warning: rules.py on_reply raised KeyError", out)

    def test_call_rules_can_skip_failed_calls(self):
        # U2 tries to reopen a ticket that does not exist: the backend refuses, the rule must not fire
        res, codes = run(self.p, ["reopen T-404"], user="U2")
        self.assertNotIn("rule:closed-stays-closed-on-reopen-by-other", codes)
        res, codes = run(self.p, ["reopen T-2"], user="U2")
        self.assertIn("rule:closed-stays-closed-on-reopen-by-other", codes)

    def test_expectations_on_one_step(self):
        # 1.0: reply_not_contains looked at every reply of the conversation
        steps = [{"say": "show T-1", "expect": {"reply_contains": ["Printer on fire"]}},
                 {"say": "hello", "expect": {"reply_not_contains": ["Printer"], "no_calls": ["get_ticket"]}}]
        self.assertEqual(run(self.p, steps)[1], [])
        steps[1]["say"] = "show T-1"
        res, codes = run(self.p, steps)
        self.assertEqual(codes, ["expect:step_no_calls", "expect:step_reply_not_contains"])
        self.assertIn('after "show T-1": the reply must not contain "Printer"', [f["detail"] for f in res["findings"]])
        self.assertEqual(report.explain(self.p, "expect:step_reply_not_contains")[0],
                         "A reply contained something a test case says must not be shown")

    def test_masked_private_values_and_visibility_without_owners(self):
        # "****2222" is how a banking product leaks; 1.0 only matched the whole value
        res, codes = run(self.p, ["leakmask"])
        self.assertEqual(codes, ["privacy_leak:users.account"])
        self.assertEqual(run(self.p, ["leakmask"], user="U2")[1], [], "the owner may see their own masked number")
        # a record nobody owns, readable only by some users (shared_with): 1.0 had no check for it
        res, codes = run(self.p, ["stock SKU-200"])
        self.assertEqual(codes, ["record_detail_leak:stock"])
        self.assertIn("which this user is not allowed to see", res["findings"][0]["detail"])
        self.assertEqual(run(self.p, ["stock SKU-200"], user="S1")[1], [])
        self.assertEqual(run(self.p, ["stock SKU-100"])[1], [])


class TestPopulationWithoutOwners(ShopCase):
    """Feedback (2 testers): "'no persona could be built' with no hint that the cause is the missing
    owner_field"; "pick.where has no user: a NameError traceback"."""

    def project(self, goals, name):
        return Project(clone(self.tmp, {"population.json": lambda _: {"goals": goals, "greetings": False}}, name))

    def test_records_that_belong_to_nobody_can_be_picked(self):
        p = self.project({"reserve": {"pick": {"entity": "stock"}, "open": ["reserve 2 {id}"],
                                      "expect": {"calls": [{"tool": "reserve", "args": {"sku": "{id}"}}]}}}, "shared")
        people = population.sample(p, seed=0)
        self.assertGreater(len(people), 5)
        self.assertTrue(all(x["slots"]["id"].startswith("SKU-") for x in people))
        self.assertEqual({x["user"] for x in people}, {"U1", "U2", "S1"})
        res = execute(p, personas=people[:6])
        self.assertTrue(all(not e["text"].startswith(("Hi", "Hello")) for e in res["events"]
                            if e["type"] == "user_msg" and e.get("act") == "open"), "greetings: false")
        self.assertTrue([e for e in res["events"] if e["type"] == "tool_call" and e["name"] == "reserve"],
                        "simulated users answered the configured confirmation wording with a yes")

    def test_where_can_use_the_user(self):
        p = self.project({"g": {"open": ["stock {id}"], "pick": {
            "entity": "stock", "where": "not rec['restricted'] or me['role'] == 'staff'", "user_where": "rec['role'] != 'member' or True"}}}, "me")
        people = population.sample(p, seed=1)
        self.assertTrue(people)
        for x in people:
            self.assertTrue(x["slots"]["id"] == "SKU-100" or x["user"] == "S1")

    def test_errors_name_the_goal(self):
        p = self.project({"gone": {"open": ["x"], "pick": {"entity": "stock", "where": "rec['qty'] > 10000"}},
                          "none": {"open": ["x"], "pick": {"entity": "payments", "user_where": "rec['role'] == 'robot'"}}}, "nogo")
        with self.assertRaises(SpecError) as cm:
            population.guided_population(p, budget=10)
        msg = str(cm.exception)
        self.assertIn("goal 'gone': no record of 'stock' (2 in the world) fits", msg)
        self.assertIn("goal 'none'", msg)
        self.assertIn("leave out owner_field", msg)
        p = self.project({"bad": {"open": ["x"], "pick": {"entity": "stock", "where": "rec['nope'] == user"}}}, "badwhere")
        with self.assertRaises(SpecError) as cm:
            population.sample(p)
        self.assertIn("goal 'bad': pick.where could not be evaluated (KeyError: 'nope')", str(cm.exception))
        self.assertIn("rec, world, day, owner, user, me", str(cm.exception))
        self.assertEqual(population.check_spec(self.project({"g": {"open": ["x"], "pick": {"entity": "tasks"}}}, "tasks"))[0][:44],
                         "goal 'g' picks from entity 'tasks', which is")


def http_target(cls="Shop", script="svc/server.py", warmup=None, **extra):
    cmd = [sys.executable, script, "{port}", cls] + ([str(warmup)] if warmup is not None else [])
    cfg = {"adapter": "http", "url": "http://127.0.0.1:{port}/chat", "reply_path": "replies", "timeout": 10,
           "env": {"BACKEND_URL": "{tools_url}"}, "start": {"command": cmd},
           "attribution_headers": {"user": "X-User", "session": ["X-Session"]}}
    cfg.update(extra)
    return cfg


class TestHttpAdapter(ShopCase):
    """Feedback (3 testers): "poptest kills only the process it started; the child kept the port and
    validate/say then hung"; "readiness counts any HTTP error as up"; "{port} is always random";
    "the product sends X-User/X-Session, not X-Poptest-*"."""

    def test_the_whole_process_group_is_stopped_and_restarted_cleanly(self):
        # the launcher starts the real server as a child; with a FIXED port every restart needs the
        # previous child to be gone, so three cases in a row only work if the group is killed
        port = pick_port()
        cfg = http_target(script="svc/launcher.py", port=port)
        d = Driver(self.p, cfg)
        try:
            for i in range(3):
                d.run_case(d.new_scope(f"s{i}"), case(["close T-1", "yes"], f"c{i}"))
            self.assertTrue(port_in_use(port))
            group = d.adapter.proc
        finally:
            d.close()
        self.assertFalse(port_in_use(port), "the launcher's child was stopped too")
        self.assertFalse(group._group_alive())
        calls = [e for e in d.log.events if e["type"] == "tool_call" and e["name"] == "update_ticket"]
        self.assertEqual(len(calls), 3)
        self.assertEqual(Checker(self.p).run(d.log.events), [])

    def test_ready_means_the_service_answers_not_that_something_answers(self):
        res = execute(self.p, http_target(warmup=0.7), cases=[case(["hello"])])
        self.assertEqual(res["findings"], [], "1.0 took the 503 during warm-up as 'up' and the first message crashed")
        self.assertEqual([e["text"] for e in res["events"] if e["type"] == "bot_msg"], ["Hello."])
        slow = http_target(warmup=30)
        slow["start"]["ready_timeout"] = 0.6
        with self.assertRaises(SpecError) as cm:
            execute(self.p, slow, cases=[case(["hello"])])
        self.assertIn("did not become ready", str(cm.exception))
        self.assertIn("last answer: HTTP 503", str(cm.exception))
        strict = http_target()
        strict["start"]["ready_status"] = 204
        strict["start"]["ready_timeout"] = 0.6
        with self.assertRaises(SpecError) as cm:
            execute(self.p, strict, cases=[case(["hello"])])
        self.assertIn("last answer: HTTP 200", str(cm.exception))

    def test_fixed_port_port_range_and_port_in_use(self):
        port = pick_port()
        d = Driver(self.p, http_target(port=port, tools_port=pick_port()))
        try:
            self.assertEqual(d.adapter.url, f"http://127.0.0.1:{port}/chat")
            self.assertEqual(d.adapter.vars["tools_port"], d.adapter.server.port)
        finally:
            d.close()
        lo = pick_port()
        d = Driver(self.p, http_target(port_range=[lo, lo + 20]))
        try:
            self.assertTrue(lo <= d.adapter.vars["port"] <= lo + 20)
            self.assertTrue(lo <= d.adapter.server.port <= lo + 20)
            self.assertNotEqual(d.adapter.vars["port"], d.adapter.server.port)
        finally:
            d.close()
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        try:
            taken = busy.getsockname()[1]
            cfg = http_target(port=taken)
            cfg["start"]["port_wait"] = 0.3
            with self.assertRaises(SpecError) as cm:
                execute(self.p, cfg, cases=[case(["hello"])])
            self.assertIn(f"port {taken} is already in use", str(cm.exception))
            with self.assertRaises(SpecError) as cm:
                Driver(self.p, http_target(tools_port=taken))
            self.assertIn(f"could not listen on port {taken}", str(cm.exception))
            with self.assertRaises(SpecError):
                pick_port(None, [taken, taken])
        finally:
            busy.close()

    def test_a_target_that_dies_at_start_is_a_clear_error(self):
        cfg = http_target()
        cfg["start"]["command"] = [sys.executable, "-c", "import sys; sys.stderr.write('no licence\\n'); sys.exit(3)"]
        with self.assertRaises(SpecError) as cm:
            execute(self.p, cfg, cases=[case(["hello"])])
        self.assertIn("target process exited at start: no licence", str(cm.exception))
        cfg["start"]["command"] = ["/no/such/program"]
        with self.assertRaises(SpecError) as cm:
            execute(self.p, cfg, cases=[case(["hello"])])
        self.assertIn("could not start the target", str(cm.exception))

    def test_the_products_own_identity_headers_attribute_calls(self):
        w = self.p.new_world()
        ev = []
        box = ToolBox(w, self.p.tools_spec, self.p.handlers, ev.append)
        box.context = {"user": "U1", "session": "driver-session"}

        def call(srv, headers):
            req = urllib.request.Request(srv.url + "/call/now", b"{}", dict({"Content-Type": "application/json"}, **headers))
            urllib.request.urlopen(req, timeout=5).close()
            return ev[-1]["acting_user"], ev[-1]["session"]
        srv = ToolServer(box, headers={"user": "X-User", "session": ["X-Session", "X-Conversation"]})
        try:
            self.assertEqual(call(srv, {"X-User": "U2", "X-Session": "s9"}), ("U2", "s9"))
            self.assertEqual(call(srv, {"X-Conversation": "c3"}), ("U1", "c3"))
            self.assertEqual(call(srv, {"X-Poptest-User": "S1", "X-User": "U2"}), ("S1", "driver-session"))
            self.assertEqual(call(srv, {}), ("U1", "driver-session"))
        finally:
            srv.close()
        plain = ToolServer(box)
        try:
            self.assertEqual(call(plain, {"X-User": "U2"}), ("U1", "driver-session"), "not mapped unless configured")
        finally:
            plain.close()
        with self.assertRaises(SpecError):
            ToolServer(box, headers={"tenant": "X-Tenant"})

    def test_bugs_and_noise_are_found_through_http(self):
        res = execute(self.p, http_target("NoisyNoCancel"), cases=[
            case(["hello", "close T-1", "no", "hello", "hello", "yes", "yes"], "n", expect={"no_calls": ["update_ticket"]})])
        self.assertEqual(sorted({f["code"] for f in res["findings"]}), ["expect:no_calls", "unconfirmed_action:close_ticket"])
        self.assertEqual(noise_stats(res["events"])["noise_replies"], 1)


class TestMutationOfServiceTargets(ShopCase):
    """Feedback (6 testers): "mutate is python-in-process only, so 'how good is my suite' is
    unavailable for cli/http targets - exactly the black-box case"."""

    CASES = [{"id": "close", "user": "U1", "steps": ["close T-1", "yes"],
              "expect": {"calls": [{"tool": "update_ticket", "args": {"fields": {"status": "closed"}}, "count": 1}]}},
             {"id": "no", "user": "U1", "steps": ["close T-1", "no", "yes"], "expect": {"no_calls": ["update_ticket"]}},
             {"id": "pay", "user": "U1", "steps": ["pay 1999 SKU-100", "yes"],
              "expect": {"calls": [{"tool": "pay", "args": {"amount_minor": 1999}}]}},
             {"id": "reserve", "user": "U1", "steps": ["reserve 8 SKU-100", "yes", "stock SKU-100"],
              "expect": {"last_reply_contains": ["32 in stock"]}},
             {"id": "late", "user": "U1", "clock": {"hour": 19}, "steps": ["reserve 8 SKU-100", "yes"],
              "expect": {"no_calls": ["reserve"]}}]

    def project(self, target, name):
        d = clone(self.tmp, {"poptest.json": lambda c: dict({k: v for k, v in c.items() if k != "noise"}, target=target)}, name)
        with open(os.path.join(d, "cases", "c.json"), "w") as f:
            json.dump(self.CASES, f)
        return Project(d), d

    def test_http_target_is_mutated_through_its_own_start_command(self):
        p, d = self.project(http_target(), "mhttp")
        src = os.path.join(d, "bot.py")
        before = read(src)
        res = mutate.mutation_score(p, src, n=6, seed=2, reps=1, jobs=3, out_dir=os.path.join(self.tmp, "mh"))
        a = res["approaches"]["cases"]
        self.assertEqual((res["adapter"], a["total"], a["clean_problem_pairs"]), ("http", 6, 0))
        self.assertGreaterEqual(a["caught"], 2, a["caught_by"])
        self.assertLess(a["caught"], 6, "a faulty copy that did not start would count all six as caught")
        self.assertTrue(all(not any(str(x).startswith("error") for x in v) for v in a["caught_by"].values()), a["caught_by"])
        self.assertEqual(read(src), before, "the original source is never touched")
        self.assertIn("Detection power", report.mutate_markdown(res))

    def test_the_command_is_redirected_to_the_copy(self):
        p, d = self.project(http_target(), "remap")
        mutant = os.path.join(self.tmp, "mutant.py")
        with open(mutant, "w") as f:
            f.write("MUTANT = True\n")
        work = os.path.join(self.tmp, "work1")
        cfg = mutate.target_for(p, mutant, os.path.join(d, "bot.py"), work)
        tree = os.path.join(work, "tree")
        self.assertEqual(cfg["cwd"], tree)
        self.assertEqual(cfg["start"]["command"][1], os.path.join(tree, "svc", "server.py"))
        self.assertEqual(read(os.path.join(tree, "bot.py")), "MUTANT = True\n")
        self.assertTrue(os.path.exists(os.path.join(tree, "tools.py")))
        # a cli target: the same treatment
        p2, d2 = self.project({"adapter": "cli", "command": [sys.executable, os.path.join("svc", "server.py")], "cwd": "."}, "cli")
        cfg = mutate.target_for(p2, mutant, os.path.join(d2, "svc", "server.py"), os.path.join(self.tmp, "work2"))
        self.assertEqual(cfg["command"][1], os.path.join(self.tmp, "work2", "tree", "server.py"))
        # a wrapper as python entry with the product in another folder (1.0: "--file must be inside ...")
        os.makedirs(os.path.join(d, "wrap"))
        with open(os.path.join(d, "wrap", "wrapper.py"), "w") as f:
            f.write("import os, sys\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
                    "from bot import Shop as Wrapped\n")
        p3, _ = self.project({"adapter": "python", "entry": "wrap/wrapper.py:Wrapped"}, "wrapper-unused")
        p3.root, p3.config = d, dict(p3.config, target={"adapter": "python", "entry": "wrap/wrapper.py:Wrapped"})
        cfg = mutate.target_for(p3, mutant, os.path.join(d, "bot.py"), os.path.join(self.tmp, "work3"))
        self.assertEqual(cfg["entry"], os.path.join(self.tmp, "work3", "tree", "wrap", "wrapper.py") + ":Wrapped")

    def test_limits_are_stated_as_clear_errors(self):
        p, d = self.project(http_target(), "limits")
        with self.assertRaises(SpecError) as cm:
            mutate.mutation_score(p, None, n=2)
        self.assertIn("say which Python source file to plant faults in", str(cm.exception))
        p2, d2 = self.project({"adapter": "http", "url": "http://127.0.0.1:9/chat"}, "running")
        with self.assertRaises(SpecError) as cm:
            mutate.mutation_score(p2, os.path.join(d2, "bot.py"), n=2, out_dir=os.path.join(self.tmp, "ml"))
        self.assertIn("an already running service cannot be mutated", str(cm.exception))
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        shutil.copy(os.path.join(d, "bot.py"), elsewhere)
        with self.assertRaises(SpecError) as cm:
            mutate.mutation_score(p, os.path.join(elsewhere, "bot.py"), n=2, out_dir=os.path.join(self.tmp, "ml2"))
        self.assertIn("would never be started", str(cm.exception))
        with open(os.path.join(d, "notes.txt"), "w") as f:
            f.write("x")
        with self.assertRaises(SpecError) as cm:
            mutate.mutation_score(p, os.path.join(d, "notes.txt"), n=2)
        self.assertIn("is not a Python file", str(cm.exception))
        rc, out = sh("mutate", "--file", "nope.py", cwd=d)
        self.assertEqual(rc, 2)
        self.assertIn("no such file", out)
        self.assertNotIn("Traceback", out)


class TestCompareLabels(unittest.TestCase):
    """Feedback (2 testers): "a row under fixes said a_hits: 0, b_hits: 4, which reads as 'B has it'"."""

    def test_a_hits_always_means_runs_of_a(self):
        p = Project(SHOP)
        fixed = case(["close T-1", "no", "yes"], "x", expect={"no_calls": ["update_ticket"]})
        res = compare.compare(p, T("NoCancel"), T("Shop"), [fixed])
        self.assertEqual(res["verdict"], "B is better than A")
        self.assertEqual({(r["code"], r["a_hits"], r["b_hits"]) for r in res["fixes"]},
                         {("expect:no_calls", 2, 0), ("unconfirmed_action:close_ticket", 2, 0)})
        md = report.compare_markdown(res)
        self.assertIn("## Fixed in B (A has the problem, B does not)", md)
        self.assertIn("| Conversation | Problem | A runs with the problem (of 2) | B runs with the problem (of 2) |", md)
        self.assertIn("| x | expect:no_calls | 2 | 0 |", md)
        back = compare.compare(p, T("Shop"), T("NoCancel"), [fixed])
        self.assertEqual({(r["a_hits"], r["b_hits"]) for r in back["regressions"]}, {(0, 2)})

    def test_noise_replies_do_not_make_a_release_look_worse_than_itself(self):
        p = Project(SHOP)
        cases = [case(["hello", "close T-1", "yes"], "a", expect={"calls": ["update_ticket"]}),
                 case(["pay 1999 SKU-100", "yes", "time"], "b", expect={"calls": ["pay"]})]
        res = compare.compare(p, T("Shop"), T("Noisy"), cases)
        self.assertEqual((res["verdict"], res["regressions"], res["noise_floor"]), ("no difference beyond noise", [], []))


class TestReleaseFiles(unittest.TestCase):
    def test_version_is_1_1_0_everywhere_and_the_changelog_exists(self):
        self.assertEqual(VERSION, "1.1.0")
        plug = load(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"))
        market = load(os.path.join(PLUGIN, "..", "..", ".claude-plugin", "marketplace.json"))
        self.assertEqual(plug["version"], "1.1.0")
        self.assertEqual(market["plugins"][0]["version"], "1.1.0")
        log = read(os.path.join(PLUGIN, "..", "..", "CHANGELOG.md"))
        self.assertIn("## 1.1.0", log)
        self.assertEqual(sh("--version")[1].strip(), "poptest 1.1.0")

    def test_the_skills_document_what_the_testers_had_to_read_the_source_for(self):
        def skill(name):
            with open(os.path.join(PLUGIN, "skills", name, "SKILL.md")) as f:
                return f.read()
        world, rules, connect = skill("build-world"), skill("write-rules"), skill("connect-target")
        cases, triage, mut = skill("generate-cases"), skill("run-and-triage"), skill("mutation-score")
        for needle in ("world.now()", "world.hour()", "start_hour", "midnight", "ToolError", "status=404",
                       "ok_from_result", "private_masks", "shared_with"):
            self.assertIn(needle, world, needle)
        self.assertNotIn("Generators: literal", world)
        for needle in ("ctx.session_messages", "ctx.args", "ctx.text", "ctx.fail(", "RULES", "question_patterns",
                       '"when"', "minor_units", "ok_only", "timedelta"):
            self.assertIn(needle, rules, needle)
        for needle in ("attribution_headers", "X-User", "tools_port", "port_range", '"port"', "process group",
                       "ready_status", "noise", "max_resends", "BACKEND_URL"):
            self.assertIn(needle, connect, needle)
        for needle in ("unknown_user", "last_reply_not_contains", '"fail"', '"hour"', "owner_field", "greetings",
                       "generator script"):
            self.assertIn(needle, cases, needle)
        for needle in ("Did not reproduce", "must not happen", "did not happen", "--replays 0", "--reruns", "flake",
                       "root cause"):
            self.assertIn(needle, triage, needle)
        for needle in ("--file", "http", "cli", "no Python source", '"mutate"'):
            self.assertIn(needle, mut, needle)
        readme = read(os.path.join(PLUGIN, "README.md"))
        for needle in ("noise", "question_patterns", "--bare", "1.1"):
            self.assertIn(needle, readme, needle)


if __name__ == "__main__":
    unittest.main()
