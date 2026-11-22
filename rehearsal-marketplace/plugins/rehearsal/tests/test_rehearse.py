"""End-to-end tests for the rehearse CLI. Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "bin" / "rehearse.py"


class Rehearse:
    def __init__(self, home):
        self.home = home
        self.env = dict(os.environ, REHEARSAL_HOME=str(home))

    def __call__(self, *args, stdin=None, ok=True):
        p = subprocess.run([sys.executable, "-I", str(CLI), *args], input=stdin, text=True,
                           capture_output=True, env=self.env, cwd=str(self.home.parent))
        if ok and p.returncode != 0:
            raise AssertionError(f"{args} failed ({p.returncode}): {p.stderr}{p.stdout}")
        if not ok and p.returncode == 0:
            raise AssertionError(f"{args} unexpectedly succeeded: {p.stdout}")
        return p

    def j(self, *args, stdin=None):
        return json.loads(self(*args, stdin=stdin).stdout)


def persona(pid, role, facts):
    return {"id": pid, "role": role, "name": pid.replace("-", " ").title(),
            "goals": ["ship safely"], "concerns": ["breakage"], "grounded_in": facts}


def finding(variant, persona_id, kind, sev, stmt, ev, arena="review", rnd=1):
    return {"arena": arena, "variant": variant, "persona": persona_id, "kind": kind,
            "severity": sev, "statement": stmt, "evidence": ev, "round": rnd}


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Rehearse(Path(self.tmp.name) / ".rehearsal")
        self.r("init")

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self):
        r = self.r
        r("world", "add-entity", "--name", "export-worker", "--type", "service", "--source", "anatomy")
        r("world", "add-fact", "--subject", "export-worker", "--predicate", "had_incident",
          "--object", "timeout on 1GB exports", "--source", "incident:INC-42", "--valid-from", "2026-03-01")
        r("world", "add-fact", "--subject", "admins", "--predicate", "complain_about",
          "--object", "not knowing when export finishes", "--source", "ticket:SUP-77", "--valid-from", "2026-06-01")
        r("world", "add-fact", "--subject", "export-worker", "--predicate", "fixed",
          "--object", "streaming writer", "--source", "pr:812", "--valid-from", "2026-10-01")

    def test_full_run(self):
        r = self.r
        self.seed()
        g = r.j("should-run", "--tags", "pii,perf", "--services", "3")
        self.assertTrue(g["rehearse"])
        self.assertFalse(r.j("should-run", "--tags", "ui")["rehearse"])

        run = r.j("new", "bulk-export", "--request-text", "Admins want bulk CSV export",
                  "--question", "Will admins adopt it without a ticket spike?",
                  "--variants", "A,B", "--variant-desc", "A=sync download", "--variant-desc", "B=async job + email")
        rid = run["id"]

        r("cast", "add", rid, "--file", "-", stdin=json.dumps([
            persona("support-lead", "stakeholder", ["F2"]),
            persona("attacker", "adversary", ["F1"])]))
        # unknown fact rejected
        r("cast", "add", rid, "--file", "-", stdin=json.dumps(persona("bad", "user", ["F99"])), ok=False)

        fs = r.j("finding", "add", rid, "--file", "-", stdin="\n".join(json.dumps(x) for x in [
            finding("A", "support-lead", "unhappy_path", "high", "Large exports time out in the browser", ["F1"]),
            finding("B", "support-lead", "objection", "medium", "Users will ask where their file is", ["F2"]),
            finding("B", "attacker", "risk", "critical", "Emailed download links can be forwarded", ["F2"], arena="threat"),
        ]))
        self.assertEqual([f["id"] for f in fs], ["R1", "R2", "T1"])
        # invented evidence rejected
        r("finding", "add", rid, "--file", "-",
          stdin=json.dumps(finding("A", "support-lead", "risk", "low", "Something vague happens here", ["F77"])), ok=False)
        # round 2 can cite round-1 findings
        r("finding", "add", rid, "--file", "-",
          stdin=json.dumps(finding("B", "attacker", "risk", "low", "Agree with R2, add a status page", ["R2"], rnd=2)))

        sarif = {"runs": [{"tool": {"driver": {"name": "Semgrep"}}, "results": [
            {"ruleId": "py.sql-injection", "level": "error", "message": {"text": "Possible SQL injection"},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "export/query.py"},
                                                 "region": {"startLine": 40}}}]}]}]}
        sp = Path(self.tmp.name) / "s.sarif"
        sp.write_text(json.dumps(sarif))
        self.assertEqual(r.j("ingest-sarif", rid, str(sp), "--variant", "B")["ingested"], 1)

        d = self.r.home / "runs" / rid
        bad = {"summary": "x", "recommended_variant": "B",
               "variants": {"A": {"verdict": "no-go"}, "B": {"verdict": "go-with-changes"}},
               "predictions": [{"id": "P1", "variant": "B", "kind": "risk", "severity": "high",
                                "likelihood": 0.7, "statement": "Forwarded links leak data", "supporting_findings": ["T9"]}]}
        (d / "report.json").write_text(json.dumps(bad))
        p = r("report", "validate", rid, ok=False)
        self.assertIn("unknown finding T9", p.stdout)
        self.assertIn("neither used nor dismissed", p.stdout)

        good = {"summary": "B wins if links are signed and expire.", "recommended_variant": "B",
                "variants": {"A": {"verdict": "no-go", "summary": "times out"},
                             "B": {"verdict": "go-with-changes", "summary": "needs signed links"}},
                "predictions": [
                    {"id": "P1", "variant": "B", "kind": "risk", "severity": "critical", "likelihood": 0.7,
                     "statement": "Forwarded email links leak export data", "supporting_findings": ["T1"]},
                    {"id": "P2", "variant": "B", "kind": "unhappy_path", "severity": "medium", "likelihood": 0.8,
                     "statement": "Admin closes the tab and cannot find the file later",
                     "acceptance": "an in-app export history shows status and a re-download link",
                     "trigger": "the admin returns after closing the tab", "supporting_findings": ["R2", "R3"]},
                    {"id": "P3", "variant": "A", "kind": "unhappy_path", "severity": "high", "likelihood": 0.9,
                     "statement": "Exports over 1GB time out in the browser",
                     "acceptance": "large exports never block the request thread", "supporting_findings": ["R1"]},
                    {"id": "P4", "variant": "B", "kind": "defect", "severity": "high", "likelihood": 0.4,
                     "statement": "SQL injection in export query builder", "supporting_findings": ["T2"]}],
                "open_questions": ["Is 24h link expiry acceptable?"]}
        (d / "report.json").write_text(json.dumps(good))
        self.assertTrue(r.j("report", "validate", rid)["valid"])
        r("report", "render", rid)
        md = (d / "report.md").read_text()
        self.assertIn("Risk heatmap", md)
        self.assertIn("Must hold", md)

        r("gate", rid, "--decision", "approve", ok=False)  # needs variant
        r("gate", rid, "--decision", "approve", "--variant", "B", "--change", "links expire after 24h")
        t = r.j("tests", "gen", rid)
        self.assertEqual(t["scenarios"], 3)  # P1, P2, P4 (P4 high severity)
        feat = (d / "tests" / "rehearsed.feature").read_text()
        self.assertIn("@P2", feat)
        self.assertIn("Then an in-app export history", feat)

        r("calibrate", "outcome", rid, "P1", "--occurred", "no")
        r("calibrate", "outcome", rid, "P2", "--occurred", "yes", "--evidence", "SUP-120")
        r("calibrate", "outcome", rid, "P4", "--occurred", "no")
        r("calibrate", "miss", rid, "--statement", "CSV breaks on unicode names", "--role", "user")
        s = r.j("calibrate", "score")
        self.assertEqual(s["overall"]["judged"], 3)
        self.assertEqual(s["overall"]["hits"], 1)
        self.assertEqual(s["overall"]["misses"], 1)
        self.assertEqual(s["overall"]["recall"], 0.5)
        self.assertIn("threat", s["by"]["arena"])
        self.assertTrue((self.r.home / "scores.json").exists())
        st = r.j("status", rid)
        self.assertIsNone(st["next"])

    def test_backtest_blocks_hindsight(self):
        r = self.r
        self.seed()
        rid = r.j("new", "old-feature", "--request-text", "past feature", "--question", "q",
                  "--as-of", "2026-05-01")["id"]
        lines = r("world", "query", "--run", rid).stdout
        self.assertIn("F1", lines)
        self.assertNotIn("F2", lines)  # recorded after the cutoff
        r("cast", "add", rid, "--file", "-", stdin=json.dumps(persona("ops", "stakeholder", ["F2"])), ok=False)
        r("cast", "add", rid, "--file", "-", stdin=json.dumps(persona("ops", "stakeholder", ["F1"])))

    def test_temporal_expire(self):
        r = self.r
        self.seed()
        r("world", "expire", "F1", "--on", "2026-10-01", "--reason", "fixed by streaming writer")
        self.assertNotIn("F1 ", r("world", "query").stdout)
        self.assertIn("F1 ", r("world", "query", "--as-of", "2026-04-01").stdout)
        self.assertIn("F1 ", r("world", "query", "--all").stdout)

    def test_budget(self):
        r = self.r
        self.seed()
        r("new", "x", "--request-text", "r", "--question", "q", "--variants", "A,B,C,D", ok=False)
        rid = r.j("new", "y", "--request-text", "r", "--question", "q")["id"]
        many = [persona(f"p{i}", "user", ["F1"]) for i in range(9)]
        r("cast", "add", rid, "--file", "-", stdin=json.dumps(many), ok=False)


if __name__ == "__main__":
    unittest.main()
