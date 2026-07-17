---
name: prompt-maturity
description: Use before doing nontrivial work (code, docs, job/script generation, analysis) when the user's request is vague, underspecified, or could reasonably be interpreted multiple ways. Scores the request against an explicit 100-point rubric across Context, Task, Format, and Constraints, shows the scorecard, and asks only the clarifying questions needed to close point gaps — repeating until the score hits the required threshold (100% by default) or the user explicitly accepts a lower score. Skip entirely for requests that are already specific, or for simple factual questions.
---

# Prompt Maturity Check

Goal: never execute against a guess when the gap is closeable with a question — and never fake precision. The confidence score must be earned by verifiable specifics, not by assumption, and it must be shown to the user, not judged silently.

## 0. Confirm the target before scoring

If it's unclear *what* is being asked — not just *how detailed* it is — resolve that first, with a single direct question, before running the rubric. This matters most when a request references a skill, file, or tool with an ambiguous verb ("check," "look at," "handle this") that could mean either "apply/use it" or "inspect/critique it." Scoring the wrong target wastes a full round and produces a scorecard nobody asked for.

## 1. Score the request against the rubric (0-25 per dimension, 100 total)

For each dimension, points come from what is **explicitly stated by the user** or **verified by you reading the actual project/files** — never from a plausible-sounding assumption. An assumption scores 0 for that dimension no matter how reasonable it feels.

**Context (0-25)** — environment, data shape, versions, existing conventions
| Points | Criteria |
|---|---|
| 0-5 | No system/data/environment info; domain is a guess |
| 6-15 | Domain named, but a critical unknown remains (e.g., version, input data shape, which existing objects/conventions apply) |
| 16-24 | Nearly complete; only a minor detail is discoverable via the codebase rather than the user |
| 25 | Every environment/data-shape fact needed is stated or verified — nothing left to invent |

**Task (0-25)** — the specific action and its boundaries
| Points | Criteria |
|---|---|
| 0-5 | Goal is a single vague verb/noun ("build a thing," "make it better") |
| 6-15 | Core action is clear; scope boundaries (what's explicitly out) are not |
| 16-24 | Action and boundaries clear; a minor edge case is unaddressed |
| 25 | Action, in-scope, and out-of-scope are all explicit |

**Format (0-25)** — desired output shape
| Points | Criteria |
|---|---|
| 0-5 | No mention of output shape at all |
| 6-15 | Rough hint ("code," "a doc") but no structure/length/style |
| 16-24 | Structure mostly specified; a minor stylistic choice is open |
| 25 | Full shape specified: artifact type, structure, length/tone, language/framework conventions |

**Constraints / success criteria (0-25)** — hard requirements and how correctness is judged
| Points | Criteria |
|---|---|
| 0-5 | No constraints, no way to verify correctness |
| 6-15 | Some constraints stated, but no explicit success criteria or error-handling expectations |
| 16-24 | Most constraints plus a success signal; a minor gap remains (e.g., performance/security limit) |
| 25 | Explicit musts/must-nots, error-handling expectations, and a concrete way to verify correctness |

**Total = sum of all four (0-100). This is the confidence score.**

## 2. Show the scorecard

Always display the rubric result as a compact table before doing anything else, e.g.:

```
Prompt Maturity Scorecard
Context:      12/25 — Nautobot named, but version and CDP input data shape unknown
Task:         18/25 — action clear, but Cable-creation scope unconfirmed
Format:       5/25  — no output shape specified
Constraints:  8/25  — no error-handling or idempotency requirement stated
TOTAL:        43/100
```

This applies even on the first pass — the user should always see the number, not just get questions out of nowhere.

## 3. Check what you can determine yourself before asking the user

Read the relevant files / grep the codebase / check project conventions first. Only unresolved gaps that require the user's input get asked about, and only if closing them would raise the score (i.e., materially change the output).

Distinguish **ambiguity** (information the user could supply that would resolve the gap) from **infeasibility** (a precondition that no amount of clarification fixes — e.g., the target project has no code yet, a required tool isn't installed). Infeasibility is a blocker to report, not a rubric gap to keep querying about; a low Context score in this case doesn't mean "ask more," it means "this can't proceed as stated."

## 4. Ask about the lowest-scoring dimensions, batched

Use `AskUserQuestion`, prioritizing dimensions with the biggest point gap first, max 10 questions per round. Prefer concrete options with a recommended default over open-ended questions — options teach the user the axes of variation.

## 5. Re-score and re-show the scorecard after every round

No fixed round cap — the target is defined by the threshold (see below), not by a number of tries. Keep rounds going as long as each round is closing real point gaps.

## 6. Threshold and override

- Default required score to proceed: **100/100**.
- If the user explicitly lowers the bar or accepts the current score ("proceed anyway," "that's good enough," "use your judgment on the rest") — stop immediately, state the accepted score plainly (e.g., "Proceeding at 78/100 — Format and Constraints gaps accepted, not resolved"), and skip step 7 (nothing to independently verify against an accepted gap), going straight to step 8. Never silently relabel an accepted partial score as 100%.
- Do not inflate scores to reach the threshold faster. If genuine ambiguity remains, the score reflects that, even after multiple rounds.

## 7. Independent verification (only when the self-assessed score hits 100/100)

A score you assigned yourself, in the same thread that did the clarifying, is not trustworthy on its own — you're motivated to see the gaps as closed because you just spent effort closing them. Before treating 100/100 as real, get a second, unbiased read:

- Use the `Agent` tool (a fresh agent, no shared context with this conversation) to independently re-score.
- Give it **only**: the original raw request, and the clarified spec (the 3-5 bullet restatement) — never your rubric table, your point values, or your reasoning. Seeing your scores would anchor it into agreeing with you instead of judging independently.
- Ask it to apply the identical rubric (paste the four dimension tables verbatim into the prompt) and return its own scorecard plus total, with no knowledge of what score is "expected."
- Reconcile:
  - Independent score also 100/100 → confirmed, proceed to step 8.
  - Independent score lower → its gap findings are the real signal (a fresh reader isn't invested in your prior clarifying rounds). Surface exactly what it flagged, ask the user any follow-up question needed to close that specific gap, then re-run this verification step.
  - Cap at 2 independent-verification rounds. If disagreement persists after that, stop, report both scores and the specific unresolved gap to the user, and let them decide whether to accept it as an override (per step 6) rather than looping indefinitely.

## 8. Confirm, then execute

Show the final scorecard (and, when step 7 ran, note that it passed independent verification), restate the clarified spec in detail for user acknowledgement.
