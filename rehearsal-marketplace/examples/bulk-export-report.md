# Rehearsal report: bulk-export

**Question:** Will admins adopt bulk export without a support-ticket spike?  
**Run:** `20261122-bulk-export`
**Recommended:** B

## Summary

Variant B answers the question well, provided links are signed and expire within 24h and admins can see export status in the app. Variant A will fail for the 30% of orgs over 50k users. This is a rehearsal of foreseeable risks, not a forecast.

## Variants

| Variant | Verdict | Summary |
|---|---|---|
| A — synchronous download | no-go | times out for large orgs (R1); worse under 10x org size |
| B — async job with email link | go-with-changes | needs expiring signed links (T1) and an in-app status page (R2) |

## Predictions

| ID | Variant | Kind | Severity | Likelihood | Statement | Evidence |
|---|---|---|---|---|---|---|
| P3 | A | unhappy_path | high | 85% | Exports for orgs over 50k users time out in the browser | R1 |
| P1 | B | risk | critical | 60% | A forwarded export email exposes the org's user list | T1 |
| P2 | B | unhappy_path | medium | 75% | Admin closes the tab and cannot find the export later | R2 |

## Unhappy paths → acceptance

- **P3 (A)** Exports for orgs over 50k users time out in the browser  
  _Must hold:_ large exports never run on the request thread
- **P2 (B)** Admin closes the tab and cannot find the export later  
  _Must hold:_ an in-app export history shows status and a re-download link

## Risk heatmap

| Variant | low | medium | high | critical |
|---|---|---|---|---|
| A | 0 | 0 | 1 | 0 |
| B | 0 | 1 | 0 | 1 |

## Open questions for the human gate

- Is 24h expiry acceptable for admins on slow approval chains?
- No static scan was run (Semgrep not installed).

## Evidence

- **R1** [review/A] _export-worker_: Synchronous exports for orgs over 50k users hit the same timeouts as INC-42 (← F1, F4)
- **R2** [review/B] _support-lead_: Admins who close the tab will open tickets asking where their file is (← F2)
- **T1** [threat/B] _forwarder_: (I) Emailed links without expiry let anyone with a forwarded email download the user list (← F3)
