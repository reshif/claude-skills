---
name: outcome-report
description: Turn a rehearsal's findings into an evidence-backed outcome report — predictions with likelihoods, unhappy paths with acceptance criteria, a verdict per variant and a recommendation — validated so nothing is invented. Part of the rehearse flow.
---

# Outcome report

Run this in the main session (or the **outcome-analyst** subagent for long runs). The analyst merges findings into **predictions**: claims about what will happen if a variant ships, each with a likelihood and the findings that support it.

CLI: see the `rehearse` skill.

## 1. Gather

`rehearse finding list <run>` and `rehearse cast list <run>`. Note persona weights: a finding from a weight-0.3 persona needs corroboration before it drives a high likelihood.

## 2. Write `.rehearsal/runs/<run>/report.json`

```json
{
  "summary": "2–4 sentences answering the outcome question, with the main caveat.",
  "recommended_variant": "B",
  "variants": {
    "A": {"verdict": "no-go", "summary": "times out above 1 GB (R1)"},
    "B": {"verdict": "go-with-changes", "summary": "needs signed, expiring links (T1)"}
  },
  "predictions": [
    {"id": "P1", "variant": "B", "kind": "unhappy_path", "severity": "medium", "likelihood": 0.8,
     "statement": "Admin closes the tab and can't find the export later",
     "trigger": "the admin returns after closing the tab",
     "acceptance": "an in-app export history shows status and a re-download link",
     "supporting_findings": ["R2", "R5"]}
  ],
  "dismissed": {"R7": "duplicate of R2"},
  "open_questions": ["Is 24h link expiry acceptable to compliance?"]
}
```

Rules the validator enforces:
- every prediction cites existing findings; every `unhappy_path` has `acceptance`;
- every high/critical finding is either used by a prediction or listed in `dismissed` with a reason;
- one entry per variant with verdict `go`, `go-with-changes` or `no-go`; `recommended_variant` is a variant or `none`.

How to set likelihood (0–1): critics share one model, so five personas repeating the same point aren't five independent witnesses. Agreement across *different fact sources* counts as corroboration; the same fact restated by many personas counts once. Conflicts between personas (one role's fix hurting another) are the most valuable output, so turn each into a prediction or an open question. Beyond that, scanner evidence raises it; a single low-weight persona with weak evidence keeps it under 0.4. Be honest: most predictions belong between 0.2 and 0.8. Merge duplicates into one prediction citing all of them.

Then evaluate the what-ifs: for each, say in the variant summary whether it changes the verdict.

## 3. Validate and render

`rehearse report render <run>` validates and writes `report.md`. On errors, fix `report.json` and rerun. Never add a finding to make validation pass.

## 4. Present

Show the user: the summary, the variant verdicts, the top 3 predictions by severity × likelihood, and the open questions, then point to `report.md` for the rest. Note once that these are rehearsed risks, not forecasts.
