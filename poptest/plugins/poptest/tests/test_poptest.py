"""Tests for poptest. Run:  python3 -m unittest discover -s tests -v   (from the plugin folder)."""
import copy
import json
import os
import shutil
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
from poptest.checks import Checker  # noqa: E402
from poptest.project import Project, normalise_case  # noqa: E402
from poptest.runner import Driver, execute, read_log, transcript  # noqa: E402
from poptest.tools import ToolBox, ToolError, ToolServer  # noqa: E402
from poptest.vocab import DEFAULT, Stance  # noqa: E402
from poptest.world import SpecError, World, apply_changes, apply_patches, diff  # noqa: E402

MINI = os.path.join(HERE, "fixtures", "mini")
EXAMPLE = os.path.join(PLUGIN, "examples", "expense-agent")
BIN = os.path.join(PLUGIN, "bin", "poptest")
V2 = "target/agent_v2.py:ExpenseAgent"


def run(project, steps, user="U1", expect=None, setup=None, target=None, cid="t"):
    case = normalise_case({"id": cid, "user": user, "steps": steps, "expect": expect or {}, "setup": setup or []})
    res = execute(project, target, cases=[case])
    return res, sorted({f["code"] for f in res["findings"]})


class MiniCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project(MINI)

    def codes(self, steps, **kw):
        return run(self.p, steps, **kw)[1]


class TestWorld(MiniCase):
    def test_seeded_generation_is_deterministic(self):
        a, b, c = World(self.p.world_spec, 3), World(self.p.world_spec, 3), World(self.p.world_spec, 4)
        self.assertEqual(a.data, b.data)
        self.assertNotEqual(a.data, c.data)
        self.assertEqual(len(a.data["users"]), 9)
        self.assertEqual(len(a.data["tickets"]), 2 + 6 * 2)

    def test_canaries_and_unique_fields(self):
        w = World(self.p.world_spec, 3)
        gen = [u for u in w.data["users"].values() if u["id"].startswith("G")]
        self.assertEqual(len({u["secret"] for u in gen}), len(gen))
        self.assertTrue(all(u["secret"].startswith("CNRY-") for u in gen))
        self.assertEqual(len({u["pin"] for u in gen}), len(gen))

    def test_clock_relative_values_and_injected_clock(self):
        w = World(self.p.world_spec, 3)
        self.assertEqual(w.get("tickets", "T901")["opened_day"], 496)
        self.assertEqual(w.day, 500)
        w.advance(days=2, hours=23)
        self.assertEqual(w.day, 502)
        w.advance(hours=1)
        self.assertEqual(w.day, 503)
        self.assertEqual(w.days_since(496), 7)

    def test_snapshot_restore(self):
        w = World(self.p.world_spec, 3)
        snap = w.snapshot()
        w.update("tickets", "T901", status="closed")
        w.add("tickets", owner="U1", title="new")
        w.advance(days=5)
        w.restore(snap)
        self.assertEqual(w.get("tickets", "T901")["status"], "open")
        self.assertEqual(len(w.data["tickets"]), 14)
        self.assertEqual(w.day, 500)

    def test_diff_apply_roundtrip_and_patches(self):
        w = World(self.p.world_spec, 3)
        before = copy.deepcopy(w.data)
        changes = apply_patches(w, [{"entity": "tickets", "id": "T901", "set": {"status": "closed", "opened_day": {"days_ago": 31}}},
                                    {"entity": "tickets", "add": {"id": "T777", "owner": "U2", "title": "x"}},
                                    {"entity": "tickets", "id": "T902", "delete": True}])
        self.assertEqual({c["op"] for c in changes}, {"set", "add", "delete"})
        self.assertEqual(w.get("tickets", "T901")["opened_day"], 469)
        apply_changes(before, changes)
        self.assertEqual(before, w.data)
        self.assertEqual(diff(before, w.data), [])

    def test_owner_lookup_and_case_insensitive_get(self):
        w = World(self.p.world_spec, 3)
        self.assertEqual(w.owner_of("tickets", "T902"), "U2")
        self.assertEqual(w.owner_of("users", "U1"), "U1")
        self.assertIsNone(w.owner_of("audit", "nope"))
        self.assertEqual(w.get("tickets", "t901")["id"], "T901")

    def test_bad_specs_are_reported(self):
        with self.assertRaises(SpecError):
            World({"entities": {"x": {"generate": {"count": 1, "fields": {"a": {"nonsense": 1}}}}}})
        with self.assertRaises(SpecError):
            World({"entities": {}})
        with self.assertRaises(SpecError):
            apply_patches(World(self.p.world_spec, 3), [{"entity": "tickets", "id": "nope", "set": {"a": 1}}])


class TestTools(MiniCase):
    def box(self):
        events = []
        w = self.p.new_world()
        tb = ToolBox(w, self.p.tools_spec, self.p.handlers, events.append)
        tb.context = {"user": "U1", "session": "s", "conv": "c"}
        return tb, w, events

    def test_call_is_logged_with_true_pre_state_and_changes(self):
        tb, w, ev = self.box()
        self.assertEqual(tb.close_ticket(ticket_id="T901"), {"ok": True})
        e = ev[-1]
        self.assertEqual((e["type"], e["name"], e["acting_user"]), ("tool_call", "close_ticket", "U1"))
        self.assertEqual(e["pre"]["ticket_id"]["status"], "open")
        self.assertIn({"entity": "tickets", "id": "T901", "op": "set", "field": "status", "old": "open", "new": "closed"},
                      e["changes"])
        self.assertTrue(any(c["entity"] == "audit" and c["op"] == "add" for c in e["changes"]))
        self.assertEqual(e["day"], 500)

    def test_positional_arguments_and_read_only(self):
        tb, w, ev = self.box()
        t = tb.get_ticket("T901")
        self.assertEqual(t["title"], "Printer on fire")
        t["title"] = "mutated by the target"
        self.assertEqual(w.get("tickets", "T901")["title"], "Printer on fire")
        self.assertEqual(ev[-1]["changes"], [])

    def test_errors_are_logged_and_raised(self):
        tb, w, ev = self.box()
        with self.assertRaises(ToolError):
            tb.no_such_tool(x=1)
        self.assertIn("unknown tool", ev[-1]["error"])
        with self.assertRaises(ToolError):
            tb.boom()
        self.assertIn("backend exploded", ev[-1]["error"])
        with self.assertRaises(ToolError):
            tb.close_ticket()
        with self.assertRaises(ToolError):
            tb.close_ticket(ticket_id="T901", extra=1)

    def test_http_server(self):
        tb, w, ev = self.box()
        srv = ToolServer(tb)
        try:
            def post(path, body, headers=None):
                req = urllib.request.Request(srv.url + path, json.dumps(body).encode(),
                                             dict({"Content-Type": "application/json"}, **(headers or {})))
                with urllib.request.urlopen(req, timeout=5) as r:
                    return json.load(r)
            with urllib.request.urlopen(srv.url + "/tools", timeout=5) as r:
                self.assertIn("close_ticket", json.load(r)["tools"])
            with urllib.request.urlopen(srv.url + "/clock", timeout=5) as r:
                self.assertEqual(json.load(r)["day"], 500)
            self.assertEqual(post("/call/get_ticket", {"ticket_id": "T902"})["result"]["owner"], "U2")
            self.assertEqual(post("/call", {"name": "close_ticket", "args": {"ticket_id": "T902"}},
                                  {"X-Poptest-User": "U2"})["result"], {"ok": True})
            self.assertEqual(ev[-1]["acting_user"], "U2")
            self.assertEqual(w.get("tickets", "T902")["status"], "closed")
            with self.assertRaises(urllib.error.HTTPError) as cm:
                post("/call/nope", {})
            self.assertEqual(cm.exception.code, 404)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                post("/call/boom", {})
            self.assertEqual(cm.exception.code, 500)  # 1.1: a handler crash is a 500; ToolError(msg, status) is 4xx
        finally:
            srv.close()


class TestStance(unittest.TestCase):
    def test_yes_no_reading(self):
        s = Stance(DEFAULT)
        for t in ["yes", "Yes, please.", "yep ok", "ok", "sure go ahead", "y", "um yes", "That's right"]:
            self.assertEqual(s(t), "yes", t)
        for t in ["no", "no, please don't", "please don't", "do not do that", "yes... actually wait, no",
                  "don’t", "yeah no dont", "not yet", "hold on", "never mind", "I'd rather not"]:
            self.assertEqual(s(t), "no", t)
        for t in ["maybe", "what?", "T901", "yesterday I called"]:
            self.assertEqual(s(t), "other", t)


class TestBuiltInChecks(MiniCase):
    def test_clean_conversation_has_no_findings(self):
        self.assertEqual(self.codes(["say:hello", "confirm:close_ticket ticket_id=T901", "yes", "say:T901 is closed"]), [])

    def test_crash_and_tool_failure(self):
        self.assertEqual(self.codes(["crash:"]), ["crash"])
        self.assertEqual(self.codes(["do:boom"]), ["crash"])

    def test_privacy_leak_of_other_users_private_fields(self):
        self.assertEqual(self.codes(["say:the code is {users.U2.secret}, ok"]), ["privacy_leak:users.secret"])
        self.assertEqual(self.codes(["say:pin {users.U2.pin}."]), ["privacy_leak:users.pin"])
        self.assertEqual(self.codes(["say:your own secret is CNRY-uma-secret and pin 4821"]), [])
        self.assertEqual(self.codes(["say:order 173502 shipped"]), [], "digits inside a longer number are not a leak")
        self.assertEqual(self.codes(["my friend's code is CNRY-ugo-secret", "say:you said CNRY-ugo-secret"]), [],
                         "echoing what the user typed is not a leak")
        self.assertEqual(self.codes(["say:{users.G3.secret}"]), ["privacy_leak:users.secret"])
        self.assertEqual(self.codes(["say:{users.U2.secret}"], user="A1"), ["privacy_leak:users.secret"],
                         "nobody else may see a private field unless shared_with says so")

    def test_record_detail_leak_needs_the_other_record_and_a_detail(self):
        self.assertEqual(self.codes(["say:T902 is '{tickets.T902.title}'"]), ["record_detail_leak:tickets"])
        self.assertEqual(self.codes(["say:T902 has priority {tickets.T902.priority}"]), ["record_detail_leak:tickets"])
        self.assertEqual(self.codes(["say:I can't find T902 on your account"]), [])
        self.assertEqual(self.codes(["say:T901 is 'Printer on fire'"]), [])
        self.assertEqual(self.codes(["say:T902 is '{tickets.T902.title}'"], user="A1"), [], "admins may see every ticket")
        self.assertEqual(self.codes(["is T902 the Laptop stolen one?", "say:T902 Laptop stolen? I can't say"]), [])

    def test_action_without_confirmation(self):
        self.assertEqual(self.codes(["do:close_ticket ticket_id=T901"]), ["unconfirmed_action:close_ticket"])
        self.assertEqual(self.codes(["confirm:close_ticket ticket_id=T901", "yes"]), [])
        self.assertEqual(self.codes(["confirm:close_ticket ticket_id=T901", "yes... actually no wait"]),
                         ["unconfirmed_action:close_ticket"])
        self.assertEqual(self.codes(["confirm:close_ticket ticket_id=T901", "no", "yes do:close_ticket ticket_id=T901"]),
                         ["unconfirmed_action:close_ticket"], "a no since the question cancels it")
        self.assertEqual(self.codes(["ask:how are you", "yes do:close_ticket ticket_id=T901"]),
                         ["unconfirmed_action:close_ticket"], "a question about something else does not count")

    def test_yes_in_another_session_does_not_confirm(self):
        steps = [{"session": "a", "say": "ask:Shall I close T901"},
                 {"session": "b", "say": "yes do:close_ticket ticket_id=T901"}]
        res, codes = run(self.p, steps)
        self.assertEqual(codes, ["unconfirmed_action:close_ticket"])
        self.assertIn("never asked", res["findings"][0]["detail"])

    def test_one_yes_covers_one_action(self):
        steps = ["confirm:close_ticket ticket_id=T901", "yes", "do:close_ticket ticket_id=T901"]
        res, codes = run(self.p, steps)
        self.assertEqual(codes, ["unconfirmed_action:close_ticket"])

    def test_confirm_mismatch(self):
        self.assertEqual(self.codes(["ask:Shall I close T999", "yes do:close_ticket ticket_id=T901"]),
                         ["confirm_mismatch:close_ticket"])

    def test_false_claim(self):
        self.assertEqual(self.codes(["say:It has been closed."]), ["false_claim:close_ticket"])
        self.assertEqual(self.codes(["confirm:close_ticket ticket_id=T901", "yes", "say:It has been closed."]), [])

    def test_wrong_user_change_and_permission_expression(self):
        steps = ["confirm:close_ticket ticket_id=T902", "yes"]
        self.assertEqual(self.codes(steps), ["wrong_user_change:close_ticket"])
        self.assertEqual(self.codes(steps, user="A1"), [], "admins are allowed by the cross_user expression")
        self.assertEqual(self.codes(["do:set_title ticket_id=T902 title=hacked"]), ["wrong_user_change:set_title"])

    def test_wrong_user_access(self):
        self.assertEqual(self.codes(["do:whoami user_id=U2"]), ["wrong_user_access:whoami"])
        self.assertEqual(self.codes(["do:whoami user_id=U1"]), [])

    def test_stated_facts_are_compared_with_true_state(self):
        self.assertEqual(self.codes(["say:T901 is closed"]), ["wrong_fact:ticket-status"])
        self.assertEqual(self.codes(["say:T901 is open"]), [])
        self.assertEqual(self.codes(["say:T901 was opened 9 days ago"]), ["wrong_fact:ticket-age"])
        self.assertEqual(self.codes(["say:T901 was opened 4 days ago"]), [])
        self.assertEqual(self.codes([{"advance": {"days": 3}}, "say:T901 was opened 7 days ago"]), [])
        self.assertEqual(self.codes([{"advance": {"days": 3}}, "say:T901 was opened 4 days ago"]), ["wrong_fact:ticket-age"])
        self.assertEqual(self.codes(["say:you have 2 open tickets"]), ["wrong_fact:open-count"])
        self.assertEqual(self.codes(["say:you have 1 open tickets"]), [])
        self.assertEqual(self.codes(["confirm:close_ticket ticket_id=T901", "yes", "say:T901 is open"]),
                         ["wrong_fact:ticket-status"], "facts follow the state as it changes")


class TestRules(MiniCase):
    def test_call_rule_with_boundary(self):
        old = [{"entity": "tickets", "id": "T901", "set": {"opened_day": {"days_ago": 31}}}]
        edge = [{"entity": "tickets", "id": "T901", "set": {"opened_day": {"days_ago": 30}}}]
        steps = ["confirm:close_ticket ticket_id=T901", "yes"]
        self.assertEqual(self.codes(steps, setup=old), ["rule:close-recent-only"])
        self.assertEqual(self.codes(steps, setup=edge), [])
        self.assertEqual(self.codes([{"advance": {"days": 27}}] + steps), ["rule:close-recent-only"])

    def test_change_rule(self):
        res, codes = run(self.p, ["do:set_status ticket_id=T901 status=pending"])
        self.assertEqual(codes, ["rule:no-reopen"])
        self.assertEqual(res["findings"][0]["why"], "Closed is final.")
        self.assertIn("'open' -> 'pending'", res["findings"][0]["detail"])

    def test_reply_rule_end_rule_and_python_hook(self):
        self.assertEqual(self.codes(["say:AAAAAAAAAAAAAAAAAAAA"]), ["rule:no-shouting"])
        self.assertEqual(self.codes(["say:a forbidden-word appears"]), ["rule:forbidden-word"])
        self.assertEqual(self.codes(["say:hi"] * 51), ["rule:too-long"])
        gone = [{"patch": [{"entity": "tickets", "id": "T902", "delete": True}]}]
        self.assertEqual(self.codes(["say:hi"] + gone), ["rule:tickets-never-vanish"])

    def test_rule_that_cannot_be_evaluated_is_a_warning_not_a_finding(self):
        p = Project(MINI)
        p.rules = dict(p.rules, invariants=[{"id": "broken", "on": "reply", "require": "undefined_name > 1"}])
        res, codes = run(p, ["say:hi"])
        self.assertEqual(codes, [])
        self.assertTrue(any("broken" in w for w in res["warnings"]))


class TestExpectations(MiniCase):
    def test_all_kinds_pass(self):
        exp = {"calls": [{"tool": "close_ticket", "args": {"ticket_id": "t901"}, "count": 1}],
               "no_calls": ["set_title", {"tool": "close_ticket", "args": {"ticket_id": "T902"}}],
               "world": [{"entity": "tickets", "id": "T901", "field": "status", "equals": "closed"},
                         {"entity": "tickets", "id": "T000", "exists": False},
                         {"expr": "len(world.data['audit']) == 1"}],
               "unchanged": [{"entity": "tickets", "id": "T902"}, "users"],
               "reply_contains": ["Shall I"], "reply_not_contains": ["CNRY"], "reply_matches": ["has been \\w+"],
               "last_reply_contains": ["has been closed"]}
        self.assertEqual(self.codes(["confirm:close_ticket ticket_id=T901", "yes"], expect=exp), [])

    def test_each_kind_fails(self):
        steps = ["confirm:close_ticket ticket_id=T901", "yes"]
        cases = {
            "expect:calls": {"calls": [{"tool": "close_ticket", "count": 2}]},
            "expect:no_calls": {"no_calls": ["close_ticket"]},
            "expect:world": {"world": [{"entity": "tickets", "id": "T901", "field": "status", "equals": "open"}]},
            "expect:unchanged": {"unchanged": ["tickets"]},
            "expect:reply_contains": {"reply_contains": ["never said"]},
            "expect:reply_not_contains": {"reply_not_contains": ["closed"]},
            "expect:last_reply_matches": {"last_reply_matches": ["^Shall"]},
        }
        for code, exp in cases.items():
            self.assertEqual(self.codes(steps, expect=exp), [code])

    def test_string_comparison_is_strict(self):
        steps = ["do:set_title ticket_id=T901 title=Printer_on_fire!"]
        exp = {"world": [{"entity": "tickets", "id": "T901", "field": "title", "equals": "Printer_on_fire"}]}
        self.assertEqual(self.codes(steps, expect=exp), ["expect:world"])


class TestCasesAndRunner(MiniCase):
    def test_groups_share_world_and_target_instance(self):
        cases = [normalise_case(c) for c in [
            {"id": "g1", "group": "g", "user": "U1", "steps": ["confirm:close_ticket ticket_id=T901", "yes"]},
            {"id": "g2", "group": "g", "user": "U1", "steps": ["count", "say:T901 is closed"],
             "expect": {"reply_contains": ["seen 3"], "world": [{"entity": "tickets", "id": "T901", "field": "status", "equals": "closed"}]}},
            {"id": "solo", "user": "U1", "steps": ["count", "say:T901 is open"], "expect": {"reply_contains": ["seen 1"]}}]]
        res = execute(self.p, cases=cases)
        self.assertEqual(res["findings"], [])
        scopes = {e["conv"]: e["scope"] for e in res["events"] if e["type"] == "conv_start"}
        self.assertEqual(scopes["g1"], scopes["g2"])
        self.assertNotEqual(scopes["g1"], scopes["solo"])

    def test_concurrent_sessions_clock_and_mid_case_patch(self):
        steps = [{"session": "a", "say": "say:one"}, {"session": "b", "user": "U2", "say": "say:two"},
                 {"advance": {"days": 2}}, {"session": "a", "say": "say:three"},
                 {"patch": [{"entity": "tickets", "id": "T901", "set": {"status": "closed"}}]},
                 {"session": "a", "say": "say:T901 is closed"}, {"close": "a"}, {"session": "a", "say": "say:again"}]
        res, codes = run(self.p, steps)
        self.assertEqual(codes, [])
        ev = res["events"]
        msgs = [(e["session"], e["user"], e["day"]) for e in ev if e["type"] == "user_msg"]
        self.assertEqual(msgs[:3], [("t:a", "U1", 500), ("t:b", "U2", 500), ("t:a", "U1", 502)])
        self.assertEqual(msgs[-1][0], "t:a#2")
        types = [e["type"] for e in ev]
        for t in ("run_start", "conv_start", "session_start", "user_msg", "bot_msg", "clock", "world_patch",
                  "session_end", "conv_end", "run_end"):
            self.assertIn(t, types)
        self.assertEqual([e["seq"] for e in ev], list(range(len(ev))))

    def test_sessions_form_is_normalised(self):
        c = normalise_case({"id": "x", "user": "U1", "sessions": [
            {"day_offset": 0, "messages": ["a"]}, {"day_offset": 2, "messages": ["b", "c"]}]})
        self.assertEqual(c["steps"], [{"session": "s1", "say": "a"}, {"close": "s1"}, {"advance": {"days": 2.0}},
                                      {"session": "s2", "say": "b"}, {"session": "s2", "say": "c"}, {"close": "s2"}])
        with self.assertRaises(SpecError):
            normalise_case({"id": "x", "steps": ["hi"]})
        with self.assertRaises(SpecError):
            normalise_case({"user": "U1", "steps": ["hi"]})

    def test_checks_need_only_the_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.jsonl")
            case = normalise_case({"id": "t", "user": "U1", "steps": ["confirm:close_ticket ticket_id=T902", "yes",
                                                                       "say:{users.U2.secret}"]})
            res = execute(self.p, cases=[case], log_path=path)
            again = Checker(self.p).run(read_log(path))
            self.assertEqual(again, json.loads(json.dumps(res["findings"])))
            self.assertEqual(len(again), 2)

    def test_empty_reply_and_transcript(self):
        res, codes = run(self.p, ["silent", "say:hello"])
        self.assertEqual(codes, [])
        lines = transcript(res["events"], "t")
        self.assertIn("User: silent", lines)
        self.assertIn("System: hello", lines)


class TestAdapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project(EXAMPLE)
        ids = ["happy-submit", "happy-approve", "negated-submit-1", "negated-submit-2", "two-windows-two-actions", "window-closes-before-yes",
               "leak-status-colleague", "new-expense-of-other"]
        cls.cases = [c for c in cls.p.load_cases() if c["id"] in ids]

    def shape(self, res):
        return [(e["type"], e.get("conv"), e.get("session"), e.get("name"), json.dumps(e.get("args"), sort_keys=True),
                 bool(e.get("changes"))) for e in res["events"] if e["type"] in ("user_msg", "tool_call", "session_start")]

    def test_python_http_and_cli_give_the_same_normalised_log(self):
        py = execute(self.p, cases=self.cases)
        http = execute(self.p, "target-http.json", cases=self.cases)
        cli = execute(self.p, "target-cli.json", cases=self.cases)
        self.assertEqual(py["findings"], [])
        self.assertEqual(http["findings"], [])
        self.assertEqual(cli["findings"], [])
        self.assertEqual(self.shape(py), self.shape(http))
        self.assertEqual(self.shape(py), self.shape(cli))
        self.assertTrue(any(e["type"] == "tool_call" and e["changes"] for e in http["events"]))

    def test_bugs_are_found_through_http_too(self):
        cfg = {"adapter": "http", "url": "http://127.0.0.1:{port}/chat",
               "start": {"command": ["python3", "target/http_server.py", "{port}", "agent_v2"]}}
        res = execute(self.p, cfg, cases=self.cases)
        codes = {f["code"] for f in res["findings"]}
        self.assertIn("record_detail_leak:expenses", codes)
        self.assertIn("unconfirmed_action:submit_expense", codes)

    def test_unreachable_http_target_is_a_crash_finding(self):
        res = execute(self.p, {"adapter": "http", "url": "http://127.0.0.1:9/chat", "timeout": 2}, cases=self.cases[:1])
        self.assertIn("crash", {f["code"] for f in res["findings"]})

    def test_cli_text_protocol_one_process_per_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "echo.py")
            with open(script, "w") as f:
                f.write("import os, sys\nn = 0\nfor line in sys.stdin:\n    n += 1\n"
                        "    print(f\"{os.environ['POPTEST_USER']} {n}: {line.strip()}\", flush=True)\n"
                        "    if line.strip() == 'die':\n        sys.exit(3)\n")
            cfg = {"adapter": "cli", "command": [sys.executable, script], "protocol": "text", "timeout": 5}
            case = normalise_case({"id": "c", "user": "E01", "steps": [
                {"session": "a", "say": "one"}, {"session": "b", "say": "two"}, {"session": "a", "say": "three"},
                {"session": "a", "say": "die"}, {"session": "b", "say": "four"}]})
            res = execute(self.p, cfg, cases=[case])
            replies = [e["text"] for e in res["events"] if e["type"] == "bot_msg"]
            self.assertEqual(replies, ["E01 1: one", "E01 1: two", "E01 2: three", "E01 3: die", "E01 2: four"])

    def test_python_function_target_and_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fn.py")
            with open(path, "w") as f:
                f.write("import time\ndef handle(user, session, text, tools):\n"
                        "    if text == 'hang':\n        time.sleep(30)\n"
                        "    return {'reply': f'{user}:{tools.today()}'}\n")
            cfg = {"adapter": "python", "entry": path + ":handle", "timeout": 0.3}
            case = normalise_case({"id": "c", "user": "E01", "steps": ["hi", "hang"]})
            res = execute(self.p, cfg, cases=[case])
            self.assertIn("E01:1000", [e["text"] for e in res["events"] if e["type"] == "bot_msg"])
            self.assertEqual([f["code"] for f in res["findings"]], ["crash"])
            self.assertIn("no answer within", res["findings"][0]["detail"])


class TestExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project(EXAMPLE)
        cls.cases = cls.p.load_cases()

    def test_clean_release_passes_every_case(self):
        res = execute(self.p, cases=self.cases)
        self.assertEqual([(f["conv"], f["code"]) for f in res["findings"]], [])
        self.assertGreaterEqual(len(self.cases), 80)

    def test_every_planted_regression_is_caught(self):
        res = execute(self.p, V2, cases=self.cases)
        by = {}
        for f in res["findings"]:
            by.setdefault(f["code"], set()).add(f["conv"])
        self.assertIn("window-61-refused", by["rule:submit-window"])           # off-by-one window
        self.assertIn("limit-500-01-refused", by["rule:submit-limit"])         # loosened limit
        self.assertIn("negated-submit-2", by["unconfirmed_action:submit_expense"])   # "please don't"
        self.assertIn("leak-status-colleague", by["record_detail_leak:expenses"])    # other people's records
        self.assertIn("yes-in-other-window", by["unconfirmed_action:submit_expense"])  # state per user, not session
        self.assertIn("window-closes-before-yes", by["rule:submit-window"])    # clock jump


class TestReplay(MiniCase):
    def test_reproduction_rate_of_a_flaky_failure(self):
        case = normalise_case({"id": "f", "user": "U1", "steps": ["flaky:0.5 say:{users.U2.secret}"]})
        rep, shown = replay.reproduce(self.p, None, case, "privacy_leak:users.secret", n=60)
        self.assertTrue(0 < rep["hits"] < 60, rep)
        self.assertAlmostEqual(rep["rate"], rep["hits"] / 60)
        self.assertIsNotNone(shown)

    def test_shrink_keeps_only_the_messages_that_matter(self):
        steps = ["say:hello", "count", "confirm:close_ticket ticket_id=T902", "say:noise", "count",
                 "confirm:close_ticket ticket_id=T902", "yes", "say:bye", "count", {"advance": {"days": 1}}, "say:late"]
        res, codes = run(self.p, steps, cid="long")
        self.assertEqual(codes, ["wrong_user_change:close_ticket"])
        case = replay.case_from_log(self.p, res["events"], "long")
        short, checks = replay.shrink(self.p, None, case, "wrong_user_change:close_ticket")
        self.assertEqual([s["say"] for s in short["steps"]], ["confirm:close_ticket ticket_id=T902", "yes"])
        self.assertLess(checks, 60)

    def test_replay_from_log_restores_world_left_by_earlier_cases(self):
        cases = [normalise_case(c) for c in [
            {"id": "first", "group": "g", "user": "U1", "steps": ["confirm:close_ticket ticket_id=T901", "yes", {"advance": {"days": 3}}]},
            {"id": "second", "group": "g", "user": "U1", "steps": ["say:T901 is open", "say:T901 was opened 4 days ago"]}]]
        res = execute(self.p, cases=cases)
        self.assertEqual({f["code"] for f in res["findings"]}, {"wrong_fact:ticket-status", "wrong_fact:ticket-age"})
        case = replay.case_from_log(self.p, res["events"], "second")
        self.assertTrue(case["setup"])
        self.assertEqual(case["clock"], {"t": 3 * 1440})
        for code in ("wrong_fact:ticket-status", "wrong_fact:ticket-age"):
            rep, _ = replay.reproduce(self.p, None, case, code, n=3)
            self.assertEqual(rep["hits"], 3)
        short, _ = replay.shrink(self.p, None, case, "wrong_fact:ticket-status")
        self.assertEqual(len(short["steps"]), 1)
        self.assertEqual(len(short["setup"]), 1, "only the status change is needed, not the audit entry")

    def test_export_writes_a_case_that_fails_again(self):
        res, _ = run(self.p, ["say:hi", "say:pin {users.U2.pin}"], cid="leaky")
        case = replay.case_from_log(self.p, res["events"], "leaky")
        short, _ = replay.shrink(self.p, None, case, "privacy_leak:users.pin")
        with tempfile.TemporaryDirectory() as tmp:
            path = replay.export_case(self.p, short, "privacy_leak:users.pin", "detail", tmp)
            loaded = self.p.load_cases([path])
            self.assertEqual(loaded[0]["family"], "regression")
            again = execute(self.p, cases=loaded)
            self.assertEqual([f["code"] for f in again["findings"]], ["privacy_leak:users.pin"])

    def test_each_kind_of_failure_has_its_own_shrink_mode(self):
        # 1.1: "did not happen" failures are shrunk too, but only conservatively (see test_v11.py)
        self.assertEqual(replay.shrink_mode("expect:calls"), "inert")
        self.assertEqual(replay.shrink_mode("goal_not_met:refund", "calls[0]"), "inert")
        self.assertEqual(replay.shrink_mode("goal_not_met:refund", "no_calls[0]"), "trim")
        self.assertEqual(replay.shrink_mode("expect:no_calls"), "trim")
        self.assertEqual(replay.shrink_mode("privacy_leak:users.pin"), "full")


class TestPopulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project(EXAMPLE)
        cls.people = population.sample(cls.p, seed=1)

    def test_covering_design_covers_every_pair(self):
        import itertools
        import random
        traits = population.traits_of(self.p)
        rows = population.covering_design(traits, random.Random(0))
        names = list(traits)
        for a, b in itertools.combinations(names, 2):
            seen = {(r[a], r[b]) for r in rows}
            self.assertEqual(len(seen), len(traits[a]) * len(traits[b]), (a, b))
        full = 1
        for v in traits.values():
            full *= len(v)
        self.assertLess(len(rows), full / 20)

    def test_personas_are_deterministic_records_with_ground_truth(self):
        again = population.sample(self.p, seed=1)
        self.assertEqual(json.dumps(self.people, sort_keys=True, default=str), json.dumps(again, sort_keys=True, default=str))
        w = self.p.new_world()
        for person in self.people:
            if person["goal"] == "submit_too_old" and person["quirk"] != "negated_no":
                rec = w.get("expenses", person["slots"]["id"])
                self.assertEqual(rec["owner"], person["user"])
                self.assertGreater(w.day - rec["incurred_day"], 60)
                self.assertEqual(person["expect"]["no_calls"][0]["args"]["expense_id"], rec["id"])
            if person["goal"] == "peek_other":
                self.assertNotEqual(w.get("expenses", person["slots"]["id"])["owner"], person["user"])

    def test_surface_makes_text_messy_but_protects_ids(self):
        goals = self.p.population["goals"]
        messy = [x for x in self.people if x["style"] == "messy" and "id" in x["slots"]]
        self.assertTrue(messy)
        changed = 0
        for person in messy:
            s = population.Surface(person, goals[person["goal"]], self.p.vocab)
            for _ in range(5):
                text = " ".join(s.render({"act": "open"}))
                self.assertIn(person["slots"]["id"], text)
                changed += text not in [t.format(**person["slots"]) for t in goals[person["goal"]]["open"]]
        self.assertGreater(changed, 0)

    def test_clean_release_has_no_firm_findings_and_buggy_release_has(self):
        clean = execute(self.p, personas=self.people)
        firm = [f for f in clean["findings"] if not f["code"].startswith("goal_not_met")]
        self.assertEqual(firm, [])
        buggy = execute(self.p, V2, personas=self.people)
        codes = {f["code"] for f in buggy["findings"]}
        self.assertIn("record_detail_leak:expenses", codes)
        self.assertTrue({"unconfirmed_action:submit_expense", "unconfirmed_action:delete_expense"} & codes)
        self.assertTrue({"rule:submit-window", "rule:submit-limit"} & codes)
        acts = {e.get("act") for e in clean["events"] if e["type"] == "user_msg"}
        self.assertTrue({"negated_no", "no_wait", "yes", "answer", "dont_know"} <= acts, acts)
        tabs = [e for e in clean["events"] if e["type"] == "session_start" and e["session"].endswith("t1")]
        self.assertTrue(tabs, "some users open a second window while an action is pending")
        users = {e["user"] for e in clean["events"] if e["type"] == "user_msg"}
        self.assertGreater(len(users), 20)
        self.assertEqual(len({e["scope"] for e in clean["events"] if "scope" in e}), 1, "one shared world")

    def test_population_failure_can_be_replayed_and_shrunk(self):
        buggy = execute(self.p, V2, personas=self.people)
        f = next(f for f in buggy["findings"] if f["code"] == "record_detail_leak:expenses")
        case = replay.case_from_log(self.p, buggy["events"], f["conv"])
        rep, _ = replay.reproduce(self.p, V2, case, f["code"], n=3)
        self.assertEqual(rep["hits"], 3)
        short, _ = replay.shrink(self.p, V2, case, f["code"])
        self.assertEqual(sum("say" in s for s in short["steps"]), 1)

    def test_coverage_guided_budget(self):
        people, info = population.guided_population(self.p, budget=450, seed=2, wave_size=20)
        self.assertGreaterEqual(info["waves"], 2)
        self.assertGreater(len(people), len(population.sample(self.p, seed=2)))
        self.assertLessEqual(info["messages_spent"], 450 + 5)
        self.assertGreater(info["distinct_paths"], 10)
        self.assertTrue(any("parent" in x for x in people))


class TestCompare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project(EXAMPLE)
        cls.cases = cls.p.load_cases(only=["boundary", "negated_phrasing", "record_detail_leak", "happy_path"])

    def test_regressions_are_reported_and_noise_floor_is_measured(self):
        res = compare.compare(self.p, "target/agent.py:ExpenseAgent", V2, self.cases)
        self.assertEqual(res["verdict"], "B is worse than A")
        self.assertEqual(res["noise_floor"], [])
        self.assertEqual(res["rule"], {"reps": 3, "min_b": 2, "max_a": 0})
        self.assertIn(("window-61-refused", "rule:submit-window"), {(r["conv"], r["code"]) for r in res["regressions"]})
        back = compare.compare(self.p, V2, "target/agent.py:ExpenseAgent", self.cases)
        self.assertEqual(back["verdict"], "B is better than A")
        md = report.compare_markdown(res)
        self.assertIn("Rule fixed before the run", md)
        self.assertIn("Noise floor", md)

    def test_same_release_shows_no_difference(self):
        res = compare.compare(self.p, V2, V2, self.cases, reps=2)
        self.assertEqual(res["verdict"], "no difference beyond noise")
        self.assertEqual(res["regressions"], [])

    def test_rule_must_be_declared_first(self):
        p = Project(EXAMPLE)
        p.config = {k: v for k, v in p.config.items() if k != "compare"}
        with self.assertRaises(SpecError):
            compare.compare(p, V2, V2, self.cases)

    def test_rule_arithmetic(self):
        rule = {"reps": 3, "min_b": 2, "max_a": 0}
        a = {("c1", "x"): 1, ("c2", "x"): 0}
        b = {("c1", "x"): 3, ("c2", "x"): 2, ("c3", "x"): 1}
        self.assertEqual([(r["conv"], r["a_hits"], r["b_hits"]) for r in compare.apply_rule(a, b, rule)], [("c2", 0, 2)])


class TestMutation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project(EXAMPLE)
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_mutants_are_valid_distinct_single_faults(self):
        src = os.path.join(EXAMPLE, "target", "agent.py")
        made, sites = mutate.make_mutants(src, os.path.join(self.tmp, "m"), n=24, seed=1)
        self.assertEqual(len(made), 24)
        self.assertGreater(sites, 100)
        self.assertGreaterEqual(len({m["kind"] for m in made}), 6)
        original = open(src).read()
        import ast
        base = ast.unparse(ast.parse(original))
        texts = set()
        for m in made:
            code = open(m["path"]).read()
            compile(code, m["path"], "exec")
            self.assertNotEqual(code, base)
            texts.add(code)
        self.assertEqual(len(texts), 24)

    def test_detection_power_per_approach_and_missed_faults(self):
        people = population.sample(self.p, seed=1)
        res = mutate.mutation_score(self.p, n=10, seed=3, approaches=("cases", "population"), reps=1,
                                    personas=people, out_dir=os.path.join(self.tmp, "score"), jobs=4)
        cases, pop = res["approaches"]["cases"], res["approaches"]["population"]
        self.assertEqual(cases["total"], 10)
        self.assertGreaterEqual(cases["detection_power"], 0.6)
        self.assertEqual(cases["caught"] + len(cases["missed"]), 10)
        self.assertEqual(sum(k["total"] for k in cases["by_kind"].values()), 10)
        self.assertGreater(pop["caught"], 0)
        md = report.mutate_markdown(res)
        self.assertIn("Detection power", md)
        self.assertIn("Faults no approach caught", md)
        for m in res["missed_by_all"]:
            self.assertIn(f"line {m['line']}", md)

    def test_a_fault_that_hangs_counts_as_caught(self):
        units, problem = mutate._eval_mutant({"project": EXAMPLE, "approach": "cases", "case_paths": None, "only": None,
                                              "personas": None, "mutant": "/nonexistent.py",
                                              "src": os.path.join(EXAMPLE, "target", "agent.py"), "reps": 1}, timeout=60)
        self.assertIsNone(units)
        self.assertTrue(problem.startswith("error"))


class TestReport(unittest.TestCase):
    def test_report_is_plain_language_with_script_rate_and_reason(self):
        p = Project(EXAMPLE)
        cases = p.load_cases(only=["negated_phrasing", "record_detail_leak", "clock", "happy_path"])
        res = execute(p, V2, cases=cases)
        problems = report.triage(p, V2, res["events"], res["findings"], replays=3)
        rep = report.build(p, "r", res["events"], res["findings"], res["warnings"], problems)
        md = report.markdown(rep)
        self.assertIn("An action was taken without a clear yes from the user", md)
        self.assertIn("One user was shown details of a record that belongs to someone else", md)
        self.assertIn("An expense older than 60 days was submitted", md)
        self.assertIn("**How often.**", md)
        self.assertIn("**Shortest way to see it**", md)
        self.assertIn("**Why it matters.**", md)
        self.assertIn("User: ", md)
        self.assertIn("the problem showed 3 time(s)", md)
        for jargon in ("oracle", "ddmin", "mutant", "persona", "scope", "seq", "canary", "tool_call", "invariant"):
            self.assertNotIn(jargon, md.lower().replace("personal", ""), jargon)
        json.dumps(rep)
        leak = next(x for x in rep["problems"] if x["code"] == "record_detail_leak:expenses")
        self.assertEqual(leak["example"]["short_messages"], 1)
        self.assertEqual(leak["replay"], {"hits": 3, "n": 3, "rate": 1.0})

    def test_clean_report(self):
        p = Project(EXAMPLE)
        res = execute(p, cases=p.load_cases(only=["happy_path"]))
        md = report.markdown(report.build(p, "r", res["events"], res["findings"], [], []))
        self.assertIn("No problems were found", md)


class TestCLI(unittest.TestCase):
    def sh(self, *args, cwd=None):
        r = subprocess.run([sys.executable, BIN, *args], cwd=cwd, capture_output=True, text=True, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def test_init_validate_run_on_a_fresh_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "proj")
            rc, out = self.sh("init", d)
            self.assertEqual(rc, 0, out)
            for f in ("poptest.json", "world.json", "tools.json", "tools.py", "rules.json", "cases", "vocab.json"):
                self.assertTrue(os.path.exists(os.path.join(d, f)), f)
            rc, out = self.sh("validate", cwd=d)
            self.assertEqual(rc, 0, out)
            self.assertIn("OK", out)
            rc, out = self.sh("run", cwd=d)
            self.assertEqual(rc, 0, out)
            self.assertTrue(os.path.exists(os.path.join(d, "runs", "run-001", "report.md")))
            self.assertTrue(os.path.exists(os.path.join(d, "runs", "run-001", "events.jsonl")))
            rc, out = self.sh("init", d)
            self.assertEqual(rc, 2, "refuses to overwrite")
            rc, out = self.sh("world", "--entity", "tasks", "--where", "rec['owner'] == 'alice'", cwd=d)
            self.assertIn("T-9001", out)
            rc, out = self.sh("say", "--user", "alice", "delete T-9001", "yes", cwd=d)
            self.assertIn("has been deleted", out)
            self.assertIn("No check fired", out)

    def test_full_flow_on_the_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "ex")
            self.assertEqual(self.sh("init", d, "--example", "expense-agent")[0], 0)
            rc, out = self.sh("run", "--name", "good", cwd=d)
            self.assertEqual(rc, 0, out)
            rc, out = self.sh("run", "--name", "bad", "--target", V2, "--only", "negated_phrasing", "cross_user",
                              "--export", cwd=d)
            self.assertEqual(rc, 1, out)
            rep = json.load(open(os.path.join(d, "runs", "bad", "report.json")))
            self.assertTrue(rep["problems"])
            saved = [x["example"]["saved_as"] for x in rep["problems"] if x["example"].get("saved_as")]
            self.assertTrue(saved and all(os.path.exists(s) for s in saved))
            rc, out = self.sh("show", "bad", cwd=d)
            self.assertIn("negated-submit-2   <- ", out)
            rc, out = self.sh("replay", "bad", "negated-submit-2", "--code", "unconfirmed_action", "-n", "3", "--shrink",
                              "--target", V2, cwd=d)
            self.assertEqual(rc, 1, out)
            self.assertIn("happened in 3 of 3 replays", out)
            rc, out = self.sh("compare", "--a", "target/agent.py:ExpenseAgent", "--b", V2, "--only", "boundary", cwd=d)
            self.assertEqual(rc, 1, out)
            self.assertIn("B is worse than A", out)
            rc, out = self.sh("mutate", "--n", "6", "--reps", "1", "--only", "boundary", "mind_change", cwd=d)
            self.assertEqual(rc, 0, out)
            self.assertIn("planted faults", out)
            rc, out = self.sh("run", "--population-only", "--budget", "150", "--replays", "0", cwd=d)
            self.assertIn("conversations", out)
            rc, out = self.sh("validate", "--project", os.path.join(tmp, "nowhere"))
            self.assertEqual(rc, 2)

    def test_validate_reports_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "proj")
            self.sh("init", d)
            with open(os.path.join(d, "cases", "bad.json"), "w") as f:
                json.dump([{"id": "x", "user": "nobody", "steps": ["hi"], "expect": {"calls": ["no_such_tool"]}}], f)
            rc, out = self.sh("validate", cwd=d)
            self.assertEqual(rc, 1)
            self.assertIn("unknown user", out)
            self.assertIn("unknown tool", out)


class TestPackaging(unittest.TestCase):
    def test_marketplace_plugin_skills_and_commands(self):
        market = json.load(open(os.path.join(PLUGIN, "..", "..", ".claude-plugin", "marketplace.json")))
        plug = json.load(open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json")))
        entry = market["plugins"][0]
        self.assertEqual(entry["name"], plug["name"])
        self.assertEqual(entry["version"], plug["version"])
        self.assertTrue(os.path.isdir(os.path.join(PLUGIN, "..", "..", entry["source"])))
        self.assertTrue(os.access(BIN, os.X_OK))
        skills = sorted(os.listdir(os.path.join(PLUGIN, "skills")))
        for need in ("poptest", "connect-target", "build-world", "write-rules", "generate-cases", "run-and-triage",
                     "compare-releases", "mutation-score"):
            self.assertIn(need, skills)
        for s in skills:
            text = open(os.path.join(PLUGIN, "skills", s, "SKILL.md")).read()
            self.assertTrue(text.startswith("---\nname: " + s + "\n"), s)
            self.assertIn("\ndescription: ", text.split("---")[1], s)
        for c in os.listdir(os.path.join(PLUGIN, "commands")):
            self.assertTrue(open(os.path.join(PLUGIN, "commands", c)).read().startswith("---\ndescription: "), c)
        self.assertIn("When NOT to use", open(os.path.join(PLUGIN, "skills", "poptest", "SKILL.md")).read())


if __name__ == "__main__":
    unittest.main()
