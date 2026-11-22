# Rehearsal — a pre-mortem stage for your software factory

Before the factory builds a big or risky request, **rehearse it**. Grounded critics attack each variant, an analyst writes an evidence-backed outcome report, you choose at a gate, and the unhappy paths become acceptance tests. After release, calibration checks the predictions against reality, so you learn which critics to trust.

This takes MiroFish's pattern (seed → ontology → personas → arenas → report agent → interviews) and applies it to software, with two changes. Critics must cite real evidence, and predictions are scored against what actually happened.

```
request ─► should-run? ─► seed world ─► cast ─► review arena ┐
                                               threat arena  ┴► outcome report ─► GATE (you)
                                                                                    │ approve
             calibrate ◄── real outcomes ◄── release ◄── factory build ◄── tests ◄──┘
```

## Install

```bash
# from a local folder
claude plugin marketplace add /path/to/rehearsal-marketplace
claude plugin install rehearsal@rehearsal-marketplace
```

Or inside Claude Code: `/plugin marketplace add /path/to/rehearsal-marketplace`, then `/plugin install rehearsal@rehearsal-marketplace`. To share it with your team, push this folder to a GitHub Enterprise repo and add that repo as the marketplace instead.

Requirements: Python 3.10+ (standard library only). Optional extras: Semgrep, STRIDE GPT, and Graphiti (`plugins/rehearsal/infra/GRAPHITI.md`).

## Use

In any repo:

```
/rehearsal:rehearse Admins want bulk CSV export of all users --variants A,B
```

Or just ask: "rehearse this request before we build it". The flow runs itself and stops at the gate for your decision.

| You'll get | Where |
|---|---|
| Outcome report: verdict per variant, predictions, risk heatmap, open questions | `.rehearsal/runs/<run>/report.md` |
| Acceptance checklist with an evidence trail | `.rehearsal/runs/<run>/tests/acceptance.md` |
| Gherkin scenarios tagged `@P#` | `.rehearsal/runs/<run>/tests/rehearsed.feature` |
| Calibration scores across runs | `.rehearsal/scores.json` |

Other entry points:
- "backtest the rehearsal on <past feature>" (`backtest` skill): **do this first, on 5–10 past features.** It tells you whether rehearsals are worth running.
- "calibrate the <feature> rehearsal" (`calibrate` skill): after a release.

## What's inside

| Piece | What it does |
|---|---|
| `bin/rehearse.py` | Stdlib CLI that holds state and enforces the rules: temporal fact store, personas, findings, SARIF ingest, report validation and rendering, gate, test generation, calibration, cost guard, budget |
| `skills/rehearse` | Orchestrator for the whole flow |
| `skills/seed-world` | Builds the fact store from anatomy/code plus tickets, incidents, analytics and ADRs |
| `skills/cast` | Grounded personas: user, stakeholder, service, adversary, weighted by past calibration |
| `skills/review-arena` | Parallel critique, then one debate round |
| `skills/threat-arena` | Adversary STRIDE pass plus Semgrep/STRIDE GPT, ingested as SARIF |
| `skills/outcome-report` | Predictions with likelihoods, verdicts, recommendation |
| `skills/paths-to-tests` | Approved variant → Gherkin + acceptance checklist |
| `skills/calibrate` | Prediction vs reality → Brier, precision, recall, persona weights |
| `skills/backtest` | Replays a past feature with the world frozen before its release |
| `agents/persona-critic`, `agents/adversary` | Critics (Sonnet). They only read the repo and output JSON lines |
| `agents/outcome-analyst` | Analyst for large runs (inherits the session model) |

## Rules the CLI enforces

- **No invented evidence.** Every persona, finding and prediction must cite ids that exist: facts `F#`, findings `R#/T#`, or `sarif:`/`file:` refs.
- **No hindsight in backtests.** With `--as-of`, anything citing a fact that wasn't true yet is rejected.
- **No silently dropped risks.** Every high or critical finding is either used by a prediction or dismissed with a reason.
- **Budget.** At most 8 personas, 2 debate rounds and 3 variants by default (edit `.rehearsal/config.json`).
- **Cost guard.** `should-run` scores tags, files and services against a threshold, so small changes skip the rehearsal.

## Tests

```bash
cd plugins/rehearsal && python3 -m unittest discover -s tests -v
```

## Honest limits

This finds *foreseeable* problems faster than a meeting would. It does not predict the future. Its value is whatever your backtests and calibration show, so measure it before you rely on it.
