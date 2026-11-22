#!/usr/bin/env python3
"""rehearse - deterministic backbone for the Rehearsal stage.

Python standard library only. Agents do the thinking; this CLI keeps the
state honest: it stores the world (a small temporal fact store), personas,
findings, the outcome report, the gate decision, generated tests and
calibration scores, and it refuses data that points at evidence that does
not exist.

State lives in ./.rehearsal (override with REHEARSAL_HOME).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

VERSION = "0.1.0"

ROLES = ("user", "stakeholder", "service", "adversary", "scanner")
KINDS = ("objection", "unhappy_path", "risk", "defect", "question")
SEVERITIES = ("low", "medium", "high", "critical")
ARENA_PREFIX = {"review": "R", "threat": "T", "product": "U", "runtime": "X"}
DECISIONS = ("approve", "revise", "kill")

DEFAULT_CONFIG = {
    "version": 1,
    "budget": {"max_personas": 8, "max_debate_rounds": 2, "max_variants": 3},
    "trigger": {
        "threshold": 5,
        "tag_weights": {
            "auth": 3, "payments": 3, "pii": 3, "migration": 3,
            "public-api": 2, "infra": 2, "data-model": 2,
            "perf": 1, "ui": 1, "integration": 1,
        },
        "files_over": 20, "files_points": 2,
        "services_at_least": 3, "services_points": 2,
    },
    "calibration": {"min_weight": 0.2},
}


class CLIError(Exception):
    pass


# ----------------------------------------------------------------- helpers
def home() -> Path:
    return Path(os.environ.get("REHEARSAL_HOME", ".rehearsal")).resolve()


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return _dt.date.today().isoformat()


def read_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise CLIError(f"missing file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CLIError(f"invalid JSON in {path}: {e}")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise CLIError(f"invalid JSON on line {n} of {path}: {e}")
    return out


def append_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def load_input(src: str):
    """Read JSON from a file path or '-' (stdin). Accepts an object, a list, or JSON lines."""
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        raise CLIError("empty input")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = [json.loads(l) for l in text.splitlines() if l.strip()]
        except json.JSONDecodeError as e:
            raise CLIError(f"input is not JSON or JSON lines: {e}")
    return data if isinstance(data, list) else [data]


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:48] or "item"


def next_id(prefix: str, existing: list) -> str:
    n = 0
    for e in existing:
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", str(e))
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1}"


def valid_date(s: str | None, field: str) -> str | None:
    if s is None:
        return None
    try:
        _dt.date.fromisoformat(s[:10])
    except ValueError:
        raise CLIError(f"{field} must be an ISO date (YYYY-MM-DD), got {s!r}")
    return s[:10]


def out(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def config() -> dict:
    cfg = read_json(home() / "config.json", default={})
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


def require_init() -> Path:
    h = home()
    if not (h / "config.json").exists():
        raise CLIError(f"not initialised: run `rehearse init` (looked in {h})")
    return h


def run_dir(run_id: str) -> Path:
    d = require_init() / "runs" / run_id
    if not (d / "run.json").exists():
        raise CLIError(f"unknown run: {run_id}")
    return d


def load_run(run_id: str) -> dict:
    return read_json(run_dir(run_id) / "run.json")


def save_run(run: dict) -> None:
    run["updated"] = now()
    write_json(run_dir(run["id"]) / "run.json", run)


# ------------------------------------------------------------------- world
def facts_path() -> Path:
    return require_init() / "world" / "facts.jsonl"


def entities_path() -> Path:
    return require_init() / "world" / "entities.json"


def fact_active(f: dict, as_of: str | None) -> bool:
    if as_of is None:
        return f.get("valid_to") is None
    vf = f.get("valid_from") or "0000-01-01"
    vt = f.get("valid_to")
    return vf <= as_of and (vt is None or vt > as_of)


def all_fact_ids() -> set:
    return {f["id"] for f in read_jsonl(facts_path())}


def cmd_world_add_entity(a):
    ents = read_json(entities_path(), default={})
    eid = a.id or slugify(a.name)
    if eid in ents and not a.update:
        raise CLIError(f"entity exists: {eid} (use --update)")
    attrs = json.loads(a.attrs) if a.attrs else {}
    ents[eid] = {"id": eid, "type": a.type, "name": a.name, "attrs": attrs,
                 "source": a.source, "recorded": now()}
    write_json(entities_path(), ents)
    out(ents[eid])


def cmd_world_add_fact(a):
    rows = []
    existing = [f["id"] for f in read_jsonl(facts_path())]
    ents = read_json(entities_path(), default={})
    items = load_input(a.file) if a.file else [{
        "subject": a.subject, "predicate": a.predicate, "object": a.object,
        "source": a.source, "valid_from": a.valid_from}]
    for it in items:
        for k in ("subject", "predicate", "object", "source"):
            if not it.get(k):
                raise CLIError(f"fact needs {k}: {it}")
        if a.strict and it["subject"] not in ents:
            raise CLIError(f"unknown subject entity {it['subject']!r} (add it first or drop --strict)")
        fid = next_id("F", existing + [r["id"] for r in rows])
        rows.append({
            "id": fid, "subject": it["subject"], "predicate": it["predicate"],
            "object": it["object"], "source": it["source"],
            "valid_from": valid_date(it.get("valid_from") or today(), "valid_from"),
            "valid_to": None, "recorded": now()})
    append_jsonl(facts_path(), rows)
    out(rows if len(rows) > 1 else rows[0])


def cmd_world_expire(a):
    facts = read_jsonl(facts_path())
    hit = None
    for f in facts:
        if f["id"] == a.fact_id:
            if f.get("valid_to"):
                raise CLIError(f"{a.fact_id} already expired on {f['valid_to']}")
            f["valid_to"] = valid_date(a.on or today(), "on")
            f["expired_reason"] = a.reason
            hit = f
    if not hit:
        raise CLIError(f"unknown fact {a.fact_id}")
    write_jsonl(facts_path(), facts)
    out(hit)


def cmd_world_query(a):
    as_of = valid_date(a.as_of, "as_of")
    if a.run and not as_of:
        as_of = load_run(a.run).get("as_of")
    facts = [f for f in read_jsonl(facts_path()) if a.all or fact_active(f, as_of)]
    if a.entity:
        facts = [f for f in facts if a.entity in (f["subject"], f["object"])]
    if a.predicate:
        facts = [f for f in facts if f["predicate"] == a.predicate]
    if a.text:
        t = a.text.lower()
        facts = [f for f in facts if t in json.dumps(f, ensure_ascii=False).lower()]
    if a.format == "lines":
        for f in facts:
            span = f"{f.get('valid_from')}..{f.get('valid_to') or 'now'}"
            print(f"{f['id']}  {f['subject']} --{f['predicate']}--> {f['object']}  [{span}; {f['source']}]")
    else:
        out(facts)


def cmd_world_stats(a):
    facts = read_jsonl(facts_path())
    ents = read_json(entities_path(), default={})
    by_type = {}
    for e in ents.values():
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    out({"entities": len(ents), "entity_types": by_type, "facts": len(facts),
         "active_facts": sum(1 for f in facts if f.get("valid_to") is None)})


# --------------------------------------------------------------- lifecycle
def cmd_init(a):
    h = home()
    (h / "runs").mkdir(parents=True, exist_ok=True)
    (h / "world").mkdir(parents=True, exist_ok=True)
    if not (h / "config.json").exists():
        write_json(h / "config.json", DEFAULT_CONFIG)
    gi = h / ".gitignore"
    if not gi.exists():
        gi.write_text("*.tmp\n", encoding="utf-8")
    out({"home": str(h), "config": str(h / "config.json")})


def cmd_should_run(a):
    cfg = config()["trigger"]
    reasons, score = [], 0
    for tag in [t.strip() for t in (a.tags or "").split(",") if t.strip()]:
        w = cfg["tag_weights"].get(tag, 0)
        if w:
            score += w
            reasons.append(f"tag {tag} (+{w})")
        else:
            reasons.append(f"tag {tag} (unknown, +0)")
    if a.files is not None and a.files > cfg["files_over"]:
        score += cfg["files_points"]
        reasons.append(f"{a.files} files touched (+{cfg['files_points']})")
    if a.services is not None and a.services >= cfg["services_at_least"]:
        score += cfg["services_points"]
        reasons.append(f"{a.services} services affected (+{cfg['services_points']})")
    if a.irreversible:
        score += cfg["threshold"]
        reasons.append("irreversible change (+threshold)")
    decision = a.force or score >= cfg["threshold"]
    out({"rehearse": decision, "score": score, "threshold": cfg["threshold"],
         "reasons": reasons + (["forced"] if a.force else [])})


def cmd_new(a):
    h = require_init()
    cfg = config()
    variants = [v.strip() for v in (a.variants or "A").split(",") if v.strip()]
    if len(variants) > cfg["budget"]["max_variants"]:
        raise CLIError(f"{len(variants)} variants exceeds budget max_variants={cfg['budget']['max_variants']}")
    if len(set(variants)) != len(variants):
        raise CLIError("variant names must be unique")
    rid = f"{_dt.date.today():%Y%m%d}-{slugify(a.slug)}"
    base, n = rid, 2
    while (h / "runs" / rid).exists():
        rid, n = f"{base}-{n}", n + 1
    d = h / "runs" / rid
    for sub in ("cast", "findings", "tests"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    request = Path(a.request).read_text(encoding="utf-8") if a.request else (a.request_text or "")
    if not request.strip():
        raise CLIError("give --request FILE or --request-text TEXT")
    (d / "request.md").write_text(request.strip() + "\n", encoding="utf-8")
    descs = {}
    for item in a.variant_desc or []:
        if "=" not in item:
            raise CLIError("--variant-desc must look like A='sync export'")
        k, v = item.split("=", 1)
        if k not in variants:
            raise CLIError(f"--variant-desc for unknown variant {k}")
        descs[k] = v
    run = {
        "id": rid, "slug": a.slug, "created": now(), "question": a.question,
        "variants": [{"name": v, "description": descs.get(v, "")} for v in variants],
        "what_ifs": [w for w in (a.what_if or [])],
        "as_of": valid_date(a.as_of, "as_of"), "backtest": bool(a.as_of),
        "stage": "seeded",
    }
    write_json(d / "run.json", run)
    out(run)


def cmd_list(a):
    h = require_init()
    rows = []
    for p in sorted((h / "runs").glob("*/run.json")):
        r = read_json(p)
        rows.append({"id": r["id"], "stage": r.get("stage"), "backtest": r.get("backtest"),
                     "question": r.get("question")})
    out(rows)


STAGES = ["seeded", "cast", "arenas", "reported", "gated", "tested", "calibrated"]


def cmd_status(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    personas = sorted(p.stem for p in (d / "cast").glob("*.json"))
    findings = {}
    for p in (d / "findings").glob("*.jsonl"):
        findings[p.stem] = len(read_jsonl(p))
    rep = d / "report.json"
    gate = read_json(d / "gate.json", default={})
    tests = sorted(p.name for p in (d / "tests").glob("*"))
    outcomes = read_json(d / "outcomes.json", default={})
    checks = {
        "personas cast": bool(personas),
        "review findings": findings.get("review", 0) > 0,
        "threat findings": findings.get("threat", 0) > 0,
        "report validated": rep.exists() and run.get("report_valid") is True,
        "gate decided": bool(gate),
        "tests generated": bool(tests),
        "outcomes recorded": bool(outcomes.get("predictions")),
    }
    nxt = next((k for k, v in checks.items() if not v), None)
    out({"run": run["id"], "stage": run.get("stage"), "backtest": run.get("backtest"),
         "as_of": run.get("as_of"), "variants": [v["name"] for v in run["variants"]],
         "personas": personas, "findings": findings, "gate": gate or None,
         "tests": tests, "checks": checks, "next": nxt})


def set_stage(run: dict, stage: str) -> None:
    cur = run.get("stage", "seeded")
    if STAGES.index(stage) > STAGES.index(cur if cur in STAGES else "seeded"):
        run["stage"] = stage


# -------------------------------------------------------------------- cast
def validate_persona(p: dict, facts: set, as_of_facts: set | None) -> list:
    errs = []
    for k in ("id", "role", "name", "goals", "concerns", "grounded_in"):
        if k not in p:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", p["id"]):
        errs.append("id must be lowercase letters, digits, dashes")
    if p["role"] not in ROLES:
        errs.append(f"role must be one of {ROLES}")
    for k in ("goals", "concerns", "grounded_in"):
        if not isinstance(p[k], list) or not p[k]:
            errs.append(f"{k} must be a non-empty list")
    for fid in p.get("grounded_in", []) if isinstance(p.get("grounded_in"), list) else []:
        if fid not in facts:
            errs.append(f"grounded_in references unknown fact {fid}")
        elif as_of_facts is not None and fid not in as_of_facts:
            errs.append(f"grounded_in uses {fid}, which is not valid at the run's as_of date (hindsight leak)")
    w = p.get("weight", 1.0)
    if not isinstance(w, (int, float)) or not 0 <= w <= 1:
        errs.append("weight must be a number between 0 and 1")
    return errs


def as_of_fact_ids(run: dict) -> set | None:
    if not run.get("as_of"):
        return None
    return {f["id"] for f in read_jsonl(facts_path()) if fact_active(f, run["as_of"])}


def cmd_cast_add(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    cfg = config()
    facts = all_fact_ids()
    asof = as_of_fact_ids(run)
    items = load_input(a.file)
    existing = {p.stem for p in (d / "cast").glob("*.json")}
    new_ids = {p.get("id") for p in items} - existing
    if len(existing) + len(new_ids) > cfg["budget"]["max_personas"]:
        raise CLIError(f"budget: max_personas={cfg['budget']['max_personas']} "
                       f"(have {len(existing)}, adding {len(new_ids)})")
    weights = read_json(home() / "scores.json", default={}).get("weights", {}).get("by_role", {})
    saved = []
    for p in items:
        errs = validate_persona(p, facts, asof)
        if errs:
            raise CLIError(f"persona {p.get('id', '?')}: " + "; ".join(errs))
        if "weight" not in p and p["role"] in weights:
            p["weight"] = weights[p["role"]]
        p.setdefault("weight", 1.0)
        write_json(d / "cast" / f"{p['id']}.json", p)
        saved.append({"id": p["id"], "role": p["role"], "weight": p["weight"]})
    set_stage(run, "cast")
    save_run(run)
    out(saved)


def cmd_cast_list(a):
    d = run_dir(a.run)
    out([read_json(p) for p in sorted((d / "cast").glob("*.json"))])


# ---------------------------------------------------------------- findings
def known_personas(d: Path) -> set:
    return {p.stem for p in (d / "cast").glob("*.json")}


def all_findings(d: Path) -> list:
    rows = []
    for p in sorted((d / "findings").glob("*.jsonl")):
        rows.extend(read_jsonl(p))
    return rows


def validate_finding(f: dict, run: dict, personas: set, facts: set, finding_ids: set,
                     asof: set | None) -> list:
    errs = []
    for k in ("arena", "variant", "persona", "kind", "statement", "severity", "evidence"):
        if k not in f:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if f["arena"] not in ARENA_PREFIX:
        errs.append(f"arena must be one of {tuple(ARENA_PREFIX)}")
    if f["variant"] not in {v["name"] for v in run["variants"]}:
        errs.append(f"unknown variant {f['variant']}")
    if not str(f["persona"]).startswith("scanner:") and f["persona"] not in personas:
        errs.append(f"unknown persona {f['persona']} (cast it first)")
    if f["kind"] not in KINDS:
        errs.append(f"kind must be one of {KINDS}")
    if f["severity"] not in SEVERITIES:
        errs.append(f"severity must be one of {SEVERITIES}")
    if not isinstance(f["evidence"], list) or not f["evidence"]:
        errs.append("evidence must be a non-empty list (fact ids, finding ids, or sarif:/file: refs)")
    else:
        for ev in f["evidence"]:
            ev = str(ev)
            if re.fullmatch(r"F\d+", ev):
                if ev not in facts:
                    errs.append(f"evidence {ev} is not a known fact")
                elif asof is not None and ev not in asof:
                    errs.append(f"evidence {ev} is not valid at as_of (hindsight leak)")
            elif re.fullmatch(r"[A-Z]\d+", ev):
                if ev not in finding_ids:
                    errs.append(f"evidence {ev} is not a known finding")
            elif not re.match(r"(sarif|file|test|run):", ev):
                errs.append(f"evidence {ev!r} must be F#, a finding id, or sarif:/file:/test:/run: ref")
    if len(str(f.get("statement", ""))) < 12:
        errs.append("statement too short to be useful")
    rnd = f.get("round", 1)
    if not isinstance(rnd, int) or rnd < 1 or rnd > config()["budget"]["max_debate_rounds"]:
        errs.append(f"round must be 1..{config()['budget']['max_debate_rounds']}")
    return errs


def cmd_finding_add(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    personas = known_personas(d)
    facts = all_fact_ids()
    asof = as_of_fact_ids(run)
    existing = all_findings(d)
    ids = [f["id"] for f in existing]
    items = load_input(a.file)
    rows = []
    for f in items:
        if a.arena:
            f.setdefault("arena", a.arena)
        f.setdefault("round", 1)
        errs = validate_finding(f, run, personas, facts, set(ids), asof)
        if errs:
            raise CLIError(f"finding {json.dumps(f)[:120]}...: " + "; ".join(errs))
        f["id"] = next_id(ARENA_PREFIX[f["arena"]], ids)
        f["recorded"] = now()
        ids.append(f["id"])
        rows.append(f)
    by_arena = {}
    for r in rows:
        by_arena.setdefault(r["arena"], []).append(r)
    for arena, rs in by_arena.items():
        append_jsonl(d / "findings" / f"{arena}.jsonl", rs)
    set_stage(run, "arenas")
    run["report_valid"] = False
    save_run(run)
    out([{"id": r["id"], "arena": r["arena"], "persona": r["persona"], "kind": r["kind"]} for r in rows])


def cmd_finding_list(a):
    d = run_dir(a.run)
    rows = all_findings(d)
    if a.arena:
        rows = [r for r in rows if r["arena"] == a.arena]
    if a.variant:
        rows = [r for r in rows if r["variant"] == a.variant]
    if a.format == "lines":
        for r in rows:
            print(f"{r['id']} [{r['arena']}/{r['variant']}] {r['persona']} {r['kind']}/{r['severity']}: "
                  f"{r['statement']}  <- {', '.join(map(str, r['evidence']))}")
    else:
        out(rows)


SARIF_LEVEL = {"error": "high", "warning": "medium", "note": "low", "none": "low"}


def cmd_ingest_sarif(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    if a.variant not in {v["name"] for v in run["variants"]}:
        raise CLIError(f"unknown variant {a.variant}")
    sarif = read_json(Path(a.sarif))
    existing = all_findings(d)
    ids = [f["id"] for f in existing]
    rows = []
    for srun in sarif.get("runs", []):
        tool = srun.get("tool", {}).get("driver", {}).get("name", "scanner")
        for res in srun.get("results", []):
            rule = res.get("ruleId", "rule")
            msg = (res.get("message") or {}).get("text", "").strip() or rule
            loc = ""
            locs = res.get("locations") or []
            if locs:
                pl = locs[0].get("physicalLocation", {})
                uri = pl.get("artifactLocation", {}).get("uri", "")
                line = pl.get("region", {}).get("startLine", "")
                loc = f"{uri}:{line}" if uri else ""
            sev = SARIF_LEVEL.get(res.get("level", "warning"), "medium")
            props = res.get("properties") or {}
            if isinstance(props.get("severity"), str) and props["severity"].lower() in SEVERITIES:
                sev = props["severity"].lower()
            fid = next_id("T", ids)
            ids.append(fid)
            rows.append({
                "id": fid, "arena": "threat", "variant": a.variant,
                "persona": f"scanner:{slugify(tool)}", "kind": "risk", "severity": sev,
                "statement": f"{msg}" + (f" ({loc})" if loc else ""),
                "evidence": [f"sarif:{rule}" + (f"@{loc}" if loc else "")],
                "round": 1, "recorded": now()})
            if a.limit and len(rows) >= a.limit:
                break
    append_jsonl(d / "findings" / "threat.jsonl", rows)
    set_stage(run, "arenas")
    run["report_valid"] = False
    save_run(run)
    out({"ingested": len(rows), "ids": [r["id"] for r in rows]})


# ------------------------------------------------------------------ report
def validate_report(rep: dict, run: dict, findings: list) -> list:
    errs = []
    fids = {f["id"] for f in findings}
    variants = {v["name"] for v in run["variants"]}
    for k in ("summary", "variants", "predictions", "recommended_variant"):
        if k not in rep:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if rep["recommended_variant"] not in variants and rep["recommended_variant"] != "none":
        errs.append(f"recommended_variant must be a variant or 'none'")
    for v in variants:
        if v not in rep["variants"]:
            errs.append(f"variants is missing an entry for {v}")
        else:
            ent = rep["variants"][v]
            if ent.get("verdict") not in ("go", "go-with-changes", "no-go"):
                errs.append(f"variant {v} verdict must be go | go-with-changes | no-go")
    used = set()
    pids = set()
    for p in rep["predictions"]:
        pid = p.get("id", "?")
        if not re.fullmatch(r"P\d+", str(pid)):
            errs.append(f"prediction id {pid} must look like P1")
        if pid in pids:
            errs.append(f"duplicate prediction id {pid}")
        pids.add(pid)
        if p.get("variant") not in variants:
            errs.append(f"{pid}: unknown variant {p.get('variant')}")
        if p.get("kind") not in KINDS:
            errs.append(f"{pid}: kind must be one of {KINDS}")
        if p.get("severity") not in SEVERITIES:
            errs.append(f"{pid}: severity must be one of {SEVERITIES}")
        lk = p.get("likelihood")
        if not isinstance(lk, (int, float)) or not 0 <= lk <= 1:
            errs.append(f"{pid}: likelihood must be 0..1")
        sup = p.get("supporting_findings")
        if not isinstance(sup, list) or not sup:
            errs.append(f"{pid}: supporting_findings must cite at least one finding")
        else:
            for s in sup:
                if s not in fids:
                    errs.append(f"{pid}: cites unknown finding {s} (no invented evidence)")
                used.add(s)
        if len(str(p.get("statement", ""))) < 12:
            errs.append(f"{pid}: statement too short")
        if p.get("kind") == "unhappy_path" and not p.get("acceptance"):
            errs.append(f"{pid}: unhappy_path needs 'acceptance' (the behaviour that must hold)")
    hi = [f["id"] for f in findings if f["severity"] in ("high", "critical")]
    dropped = [h for h in hi if h not in used and h not in rep.get("dismissed", {})]
    if dropped:
        errs.append("high/critical findings neither used nor dismissed with a reason: " + ", ".join(dropped))
    for k in rep.get("dismissed", {}):
        if k not in fids:
            errs.append(f"dismissed references unknown finding {k}")
    return errs


def cmd_report_validate(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    rep = read_json(d / "report.json")
    errs = validate_report(rep, run, all_findings(d))
    run["report_valid"] = not errs
    if not errs:
        set_stage(run, "reported")
    save_run(run)
    if errs:
        out({"valid": False, "errors": errs})
        return 1
    out({"valid": True, "predictions": len(rep["predictions"])})
    return 0


def render_report(rep: dict, run: dict, findings: list) -> str:
    fmap = {f["id"]: f for f in findings}
    L = [f"# Rehearsal report: {run['slug']}", ""]
    L += [f"**Question:** {run.get('question') or '-'}  ",
          f"**Run:** `{run['id']}`" + (f" · backtest as of {run['as_of']}" if run.get("backtest") else ""),
          f"**Recommended:** {rep['recommended_variant']}", "", "## Summary", "", rep["summary"], ""]
    L += ["## Variants", "", "| Variant | Verdict | Summary |", "|---|---|---|"]
    desc = {v["name"]: v.get("description", "") for v in run["variants"]}
    for v, ent in rep["variants"].items():
        name = f"{v}" + (f" — {desc.get(v)}" if desc.get(v) else "")
        L.append(f"| {name} | {ent.get('verdict')} | {ent.get('summary', '').replace('|', '/')} |")
    L.append("")
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    preds = sorted(rep["predictions"], key=lambda p: (p["variant"], order[p["severity"]], -p["likelihood"]))
    L += ["## Predictions", "", "| ID | Variant | Kind | Severity | Likelihood | Statement | Evidence |",
          "|---|---|---|---|---|---|---|"]
    for p in preds:
        ev = ", ".join(p["supporting_findings"])
        L.append(f"| {p['id']} | {p['variant']} | {p['kind']} | {p['severity']} | {p['likelihood']:.0%} | "
                 f"{p['statement'].replace('|', '/')} | {ev} |")
    L.append("")
    up = [p for p in preds if p["kind"] == "unhappy_path"]
    if up:
        L += ["## Unhappy paths → acceptance", ""]
        for p in up:
            L.append(f"- **{p['id']} ({p['variant']})** {p['statement']}  \n  _Must hold:_ {p['acceptance']}")
        L.append("")
    L += ["## Risk heatmap", "", "| Variant | " + " | ".join(SEVERITIES) + " |",
          "|---|" + "---|" * len(SEVERITIES)]
    for v in rep["variants"]:
        cells = [str(sum(1 for p in preds if p["variant"] == v and p["severity"] == s)) for s in SEVERITIES]
        L.append(f"| {v} | " + " | ".join(cells) + " |")
    L.append("")
    if rep.get("open_questions"):
        L += ["## Open questions for the human gate", ""] + [f"- {q}" for q in rep["open_questions"]] + [""]
    if rep.get("dismissed"):
        L += ["## Dismissed findings", ""] + [f"- {k}: {v}" for k, v in rep["dismissed"].items()] + [""]
    L += ["## Evidence", ""]
    cited = sorted({s for p in preds for s in p["supporting_findings"]}, key=lambda x: (x[0], int(x[1:])))
    for c in cited:
        f = fmap[c]
        L.append(f"- **{c}** [{f['arena']}/{f['variant']}] _{f['persona']}_: {f['statement']} "
                 f"(← {', '.join(map(str, f['evidence']))})")
    L.append("")
    return "\n".join(L)


def cmd_report_render(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    rep = read_json(d / "report.json")
    errs = validate_report(rep, run, all_findings(d))
    if errs:
        out({"valid": False, "errors": errs})
        return 1
    md = render_report(rep, run, all_findings(d))
    (d / "report.md").write_text(md, encoding="utf-8")
    run["report_valid"] = True
    set_stage(run, "reported")
    save_run(run)
    out({"written": str(d / "report.md")})
    return 0


# -------------------------------------------------------------------- gate
def cmd_gate(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    if not run.get("report_valid"):
        raise CLIError("report is not validated; run `rehearse report render` first")
    variants = {v["name"] for v in run["variants"]}
    if a.decision == "approve" and a.variant not in variants:
        raise CLIError(f"approve needs --variant, one of {sorted(variants)}")
    g = {"decision": a.decision, "variant": a.variant, "note": a.note or "",
         "changes": a.change or [], "by": a.by, "at": now()}
    write_json(d / "gate.json", g)
    set_stage(run, "gated")
    save_run(run)
    out(g)


# ------------------------------------------------------------------- tests
def gherkin_escape(s: str) -> str:
    return " ".join(str(s).split())


def cmd_tests_gen(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    gate = read_json(d / "gate.json", default={})
    if gate.get("decision") != "approve" and not a.variant:
        raise CLIError("no approved variant at the gate; pass --variant to generate anyway")
    variant = a.variant or gate["variant"]
    rep = read_json(d / "report.json")
    preds = [p for p in rep["predictions"] if p["variant"] == variant
             and p["kind"] in ("unhappy_path", "defect", "risk")
             and (p["likelihood"] >= a.min_likelihood or p["severity"] in ("high", "critical"))]
    if not preds:
        raise CLIError("no qualifying predictions for that variant")
    feat = [f"# Generated by rehearse from run {run['id']} (variant {variant}).",
            "# Steps are intent, not glue: the factory turns each scenario into real tests.",
            f"@rehearsal @run-{run['id']}",
            f"Feature: {gherkin_escape(run['slug'])} — rehearsed unhappy paths", "",
            f"  Background:", f"    Given variant {variant} is implemented as approved at the gate", ""]
    ac = [f"# Acceptance criteria — {run['slug']} (variant {variant})", "",
          f"From rehearsal `{run['id']}`. Each item traces to a prediction and its evidence.", ""]
    for p in preds:
        must = p.get("acceptance") or f"the system prevents or handles: {p['statement']}"
        feat += [f"  @{p['id']} @{p['severity']}",
                 f"  Scenario: {p['id']} {gherkin_escape(p['statement'])[:110]}",
                 f"    Given the conditions described in {p['id']}",
                 f"    When {gherkin_escape(p.get('trigger') or 'that situation occurs')}",
                 f"    Then {gherkin_escape(must)}", ""]
        ac.append(f"- [ ] **{p['id']}** ({p['severity']}, {p['likelihood']:.0%}) {must}  \n"
                  f"  _Why:_ {p['statement']} — evidence {', '.join(p['supporting_findings'])}")
    for ch in gate.get("changes", []):
        ac.append(f"- [ ] **gate change** {ch}")
    (d / "tests" / "rehearsed.feature").write_text("\n".join(feat) + "\n", encoding="utf-8")
    (d / "tests" / "acceptance.md").write_text("\n".join(ac) + "\n", encoding="utf-8")
    set_stage(run, "tested")
    save_run(run)
    out({"scenarios": len(preds), "files": [str(d / "tests" / "rehearsed.feature"),
                                            str(d / "tests" / "acceptance.md")]})


# -------------------------------------------------------------- calibration
def cmd_outcome(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    rep = read_json(d / "report.json")
    pids = {p["id"] for p in rep["predictions"]}
    oc = read_json(d / "outcomes.json", default={"predictions": {}, "misses": []})
    if a.prediction not in pids:
        raise CLIError(f"unknown prediction {a.prediction}")
    oc["predictions"][a.prediction] = {"occurred": a.occurred == "yes", "evidence": a.evidence or "",
                                       "at": now()}
    write_json(d / "outcomes.json", oc)
    set_stage(run, "calibrated")
    save_run(run)
    out(oc["predictions"][a.prediction])


def cmd_miss(a):
    d = run_dir(a.run)
    run = load_run(a.run)
    oc = read_json(d / "outcomes.json", default={"predictions": {}, "misses": []})
    if a.severity not in SEVERITIES:
        raise CLIError(f"severity must be one of {SEVERITIES}")
    oc["misses"].append({"statement": a.statement, "severity": a.severity,
                         "should_have_caught": a.role or "", "evidence": a.evidence or "", "at": now()})
    write_json(d / "outcomes.json", oc)
    set_stage(run, "calibrated")
    save_run(run)
    out({"misses": len(oc["misses"])})


def cmd_score(a):
    h = require_init()
    cfg = config()
    runs = [a.run] if a.run else [p.parent.name for p in sorted((h / "runs").glob("*/run.json"))]
    agg = {"arena": {}, "role": {}, "persona": {}}
    total = {"judged": 0, "hits": 0, "false_alarms": 0, "misses": 0, "brier_sum": 0.0}
    miss_by_role = {}
    used_runs = []
    for rid in runs:
        d = h / "runs" / rid
        oc = read_json(d / "outcomes.json", default=None) if (d / "outcomes.json").exists() else None
        if not oc or not (d / "report.json").exists():
            continue
        used_runs.append(rid)
        rep = read_json(d / "report.json")
        fmap = {f["id"]: f for f in all_findings(d)}
        cast = {p.stem: read_json(p) for p in (d / "cast").glob("*.json")}
        for p in rep["predictions"]:
            o = oc["predictions"].get(p["id"])
            if o is None:
                continue
            y = 1.0 if o["occurred"] else 0.0
            brier = (p["likelihood"] - y) ** 2
            flagged = p["likelihood"] >= 0.5
            total["judged"] += 1
            total["brier_sum"] += brier
            total["hits"] += int(flagged and y == 1)
            total["false_alarms"] += int(flagged and y == 0)
            keys = {"arena": set(), "role": set(), "persona": set()}
            for s in p["supporting_findings"]:
                f = fmap.get(s)
                if not f:
                    continue
                keys["arena"].add(f["arena"])
                keys["persona"].add(f["persona"])
                role = cast.get(f["persona"], {}).get("role") or ("scanner" if str(f["persona"]).startswith("scanner:") else "unknown")
                keys["role"].add(role)
            for dim, ks in keys.items():
                for k in ks:
                    b = agg[dim].setdefault(k, {"judged": 0, "hits": 0, "false_alarms": 0, "brier_sum": 0.0})
                    b["judged"] += 1
                    b["brier_sum"] += brier
                    b["hits"] += int(flagged and y == 1)
                    b["false_alarms"] += int(flagged and y == 0)
        for m in oc.get("misses", []):
            total["misses"] += 1
            r = m.get("should_have_caught") or "unassigned"
            miss_by_role[r] = miss_by_role.get(r, 0) + 1

    def finish(b):
        flagged = b["hits"] + b["false_alarms"]
        res = {"judged": b["judged"], "hits": b["hits"], "false_alarms": b["false_alarms"],
               "brier": round(b["brier_sum"] / b["judged"], 3) if b["judged"] else None,
               "precision": round(b["hits"] / flagged, 3) if flagged else None}
        return res

    summary = finish(total)
    summary["misses"] = total["misses"]
    caught = total["hits"]
    summary["recall"] = round(caught / (caught + total["misses"]), 3) if (caught + total["misses"]) else None
    dims = {dim: {k: finish(v) for k, v in vals.items()} for dim, vals in agg.items()}
    for role, n in miss_by_role.items():
        dims["role"].setdefault(role, {"judged": 0, "hits": 0, "false_alarms": 0, "brier": None, "precision": None})
        dims["role"][role]["misses"] = n
    minw = cfg["calibration"]["min_weight"]
    weights = {}
    for role, s in dims["role"].items():
        if s.get("brier") is None or s["judged"] < 3:
            continue
        weights[role] = round(max(minw, min(1.0, 1.0 - s["brier"])), 2)
    result = {"runs": used_runs, "overall": summary, "by": dims,
              "weights": {"by_role": weights, "note": "roles with fewer than 3 judged predictions keep weight 1.0"},
              "computed": now()}
    if not a.run:
        write_json(h / "scores.json", result)
    out(result)


# --------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rehearse", description=__doc__.split("\n")[0])
    p.add_argument("--version", action="version", version=VERSION)
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("init", help="create .rehearsal/ in the current repo").set_defaults(fn=cmd_init)

    s = sp.add_parser("should-run", help="cost guard: is this request worth rehearsing?")
    s.add_argument("--tags", help="comma list, e.g. auth,payments,migration")
    s.add_argument("--files", type=int, help="files the change is expected to touch")
    s.add_argument("--services", type=int, help="services/modules affected")
    s.add_argument("--irreversible", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_should_run)

    s = sp.add_parser("new", help="start a rehearsal run")
    s.add_argument("slug")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--request", help="file with the request/spec")
    g.add_argument("--request-text")
    s.add_argument("--question", required=True, help="the outcome question to answer")
    s.add_argument("--variants", help="comma list, default A")
    s.add_argument("--variant-desc", action="append", help="A='synchronous export' (repeatable)")
    s.add_argument("--what-if", action="append", help="scenario to stress each variant with (repeatable)")
    s.add_argument("--as-of", help="backtest: only facts valid on this date may be used")
    s.set_defaults(fn=cmd_new)

    sp.add_parser("list", help="list runs").set_defaults(fn=cmd_list)
    s = sp.add_parser("status", help="where a run stands and what is next")
    s.add_argument("run")
    s.set_defaults(fn=cmd_status)

    w = sp.add_parser("world", help="the temporal fact store").add_subparsers(dest="wcmd", required=True)
    s = w.add_parser("add-entity")
    s.add_argument("--name", required=True)
    s.add_argument("--type", required=True, help="e.g. service, module, user-segment, team, system")
    s.add_argument("--id")
    s.add_argument("--attrs", help="JSON object")
    s.add_argument("--source", required=True, help="where this came from: anatomy, ticket:123, file:path")
    s.add_argument("--update", action="store_true")
    s.set_defaults(fn=cmd_world_add_entity)
    s = w.add_parser("add-fact")
    s.add_argument("--subject")
    s.add_argument("--predicate")
    s.add_argument("--object")
    s.add_argument("--source")
    s.add_argument("--valid-from", help="YYYY-MM-DD (default today)")
    s.add_argument("--file", help="JSON/JSONL of facts, or - for stdin")
    s.add_argument("--strict", action="store_true", help="subject must be a known entity")
    s.set_defaults(fn=cmd_world_add_fact)
    s = w.add_parser("expire")
    s.add_argument("fact_id")
    s.add_argument("--on")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_world_expire)
    s = w.add_parser("query")
    s.add_argument("--entity")
    s.add_argument("--predicate")
    s.add_argument("--text")
    s.add_argument("--as-of")
    s.add_argument("--run", help="use the run's as_of date")
    s.add_argument("--all", action="store_true", help="include expired facts")
    s.add_argument("--format", choices=("json", "lines"), default="lines")
    s.set_defaults(fn=cmd_world_query)
    w.add_parser("stats").set_defaults(fn=cmd_world_stats)

    c = sp.add_parser("cast", help="personas").add_subparsers(dest="ccmd", required=True)
    s = c.add_parser("add")
    s.add_argument("run")
    s.add_argument("--file", required=True, help="JSON/JSONL persona(s), or -")
    s.set_defaults(fn=cmd_cast_add)
    s = c.add_parser("list")
    s.add_argument("run")
    s.set_defaults(fn=cmd_cast_list)

    f = sp.add_parser("finding", help="arena findings").add_subparsers(dest="fcmd", required=True)
    s = f.add_parser("add")
    s.add_argument("run")
    s.add_argument("--file", required=True, help="JSON/JSONL finding(s), or -")
    s.add_argument("--arena", choices=tuple(ARENA_PREFIX))
    s.set_defaults(fn=cmd_finding_add)
    s = f.add_parser("list")
    s.add_argument("run")
    s.add_argument("--arena")
    s.add_argument("--variant")
    s.add_argument("--format", choices=("json", "lines"), default="lines")
    s.set_defaults(fn=cmd_finding_list)

    s = sp.add_parser("ingest-sarif", help="turn scanner SARIF into threat findings")
    s.add_argument("run")
    s.add_argument("sarif")
    s.add_argument("--variant", required=True)
    s.add_argument("--limit", type=int, default=0)
    s.set_defaults(fn=cmd_ingest_sarif)

    r = sp.add_parser("report", help="outcome report").add_subparsers(dest="rcmd", required=True)
    s = r.add_parser("validate")
    s.add_argument("run")
    s.set_defaults(fn=cmd_report_validate)
    s = r.add_parser("render")
    s.add_argument("run")
    s.set_defaults(fn=cmd_report_render)

    s = sp.add_parser("gate", help="record the human decision")
    s.add_argument("run")
    s.add_argument("--decision", choices=DECISIONS, required=True)
    s.add_argument("--variant")
    s.add_argument("--note")
    s.add_argument("--change", action="append", help="change required before build (repeatable)")
    s.add_argument("--by", default="human")
    s.set_defaults(fn=cmd_gate)

    t = sp.add_parser("tests", help="unhappy paths -> tests").add_subparsers(dest="tcmd", required=True)
    s = t.add_parser("gen")
    s.add_argument("run")
    s.add_argument("--variant")
    s.add_argument("--min-likelihood", type=float, default=0.3)
    s.set_defaults(fn=cmd_tests_gen)

    k = sp.add_parser("calibrate", help="predicted vs actual").add_subparsers(dest="kcmd", required=True)
    s = k.add_parser("outcome")
    s.add_argument("run")
    s.add_argument("prediction")
    s.add_argument("--occurred", choices=("yes", "no"), required=True)
    s.add_argument("--evidence", help="ticket, incident, metric link")
    s.set_defaults(fn=cmd_outcome)
    s = k.add_parser("miss", help="a real problem the rehearsal did not predict")
    s.add_argument("run")
    s.add_argument("--statement", required=True)
    s.add_argument("--severity", default="medium")
    s.add_argument("--role", help="which persona role should have caught it")
    s.add_argument("--evidence")
    s.set_defaults(fn=cmd_miss)
    s = k.add_parser("score")
    s.add_argument("--run", help="score one run only (does not update weights)")
    s.set_defaults(fn=cmd_score)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rc = args.fn(args)
        return rc or 0
    except CLIError as e:
        print(f"rehearse: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
