# Rehearsal report: admin-reports

**Question:** Will admin reports run reliably for all org sizes?  
**Run:** `20261122-admin-reports` · backtest as of 2026-02-20
**Recommended:** none

## Summary

No: synchronous generation will time out for large orgs and retries will multiply load. Rehearsal of foreseeable risks, not a forecast.

## Variants

| Variant | Verdict | Summary |
|---|---|---|
| A — generate synchronously on click | no-go | in-request build fails for large orgs (P1) |

## Predictions

| ID | Variant | Kind | Severity | Likelihood | Statement | Evidence |
|---|---|---|---|---|---|---|
| P1 | A | unhappy_path | critical | 80% | Reports for large orgs exceed the gateway timeout because the CSV is built in the request | R1 |
| P2 | A | risk | high | 60% | Admins retry timed-out reports and multiply DB load with no backpressure | R4 |
| P3 | A | risk | high | 50% | Concurrent large reports exhaust web-process memory and degrade unrelated traffic | R2 |

## Unhappy paths → acceptance

- **P1 (A)** Reports for large orgs exceed the gateway timeout because the CSV is built in the request  
  _Must hold:_ reports never build inside the HTTP request

## Risk heatmap

| Variant | low | medium | high | critical |
|---|---|---|---|---|
| A | 0 | 0 | 2 | 1 |

## Dismissed findings

- R3: concerns a job-queue fallback that was not built

## Evidence

- **R1** [review/A] _sre_: Building the full all-users CSV in memory inside the HTTP request means large orgs will exceed gateway/request timeouts and exhaust process memory. (← F1)
- **R2** [review/A] _sre_: Concurrent admin clicks each hold a whole in-memory CSV in a web-serving process, so a few large-org reports can OOM request-serving capacity and degrade unrelated traffic. (← F1)
- **R4** [review/A] _sre_: When the synchronous request times out mid-build, admins click again and retry, multiplying load on the same expensive path with no dedupe or backpressure. (← F1)
