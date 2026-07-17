---
name: spec-readiness
description: Use before doing nontrivial work (code, docs, job/script generation, analysis) when the user's request is vague, underspecified, or could reasonably be interpreted multiple ways. Scores the request against an explicit 100-point rubric across Context, Task, Format, and Constraints — each dimension must also independently clear a floor (≥20) so one severe gap can't hide behind strong scores elsewhere, and destructive/irreversible tasks require a full Constraints score regardless of the sum. States the biggest gaps in plain language (raw point values stay secondary, never the headline), and asks only the clarifying questions needed to close them — repeating until the score hits the required threshold (100% by default) or the user explicitly accepts a lower score. Once self-assessed at 100/100, a fresh independent agent re-scores the request from scratch (re-checking evidence, not just re-reading prose) to catch self-grading bias before execution. Skip entirely for requests that are already specific, or for simple factual questions.
---

# Spec Readiness Check

Goal: never execute against a guess when the gap is closeable with a question — and never fake precision. The confidence score must be earned by verifiable specifics, not by assumption, and it must be shown to the user, not judged silently.

Talk about the work, not the mechanism. Describe what's actually unresolved or at risk, in the language a domain expert would use — never narrate the skill's own process back at the user ("this proves step 7's value," "the rubric caught X"). The scoring and rounds are how you reason internally; what the user sees is plain language about their request.

## 0. Confirm the target before scoring

If it's unclear *what* is being asked — not just *how detailed* it is — resolve that first, with a single direct question, before running the rubric. This matters most when a request references a skill, file, or tool with an ambiguous verb ("check," "look at," "handle this") that could mean either "apply/use it" or "inspect/critique it." Scoring the wrong target wastes a full round and produces a scorecard nobody asked for.

## 1. Score the request against the rubric (0-25 per dimension, 100 total)

For each dimension, points come only from what is **explicitly stated by the user** or **verified by you reading the actual project/files** — a plausible-sounding assumption scores 0 for that dimension, no matter how reasonable it feels.

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

When a dimension falls within a multi-point band (0-5, 6-15, 16-24), pick the specific value by counting how many concretely unresolved sub-items remain within that dimension — fewer remaining unknowns scores toward the top of the band, more toward the bottom. Pick deliberately, not out of politeness: an arbitrary choice makes "biggest point gap" in Step 4 meaningless.

## 2. Lead with plain language; keep the numbers secondary

State the biggest gaps in plain English first — what's actually unknown or unresolved, in terms a domain expert would use, not rubric terminology ("dimension," "band," "floor"). Order biggest-to-smallest. For example:

> Before I start: I don't know the output format you want, and I'm not sure if creating Cable connections is in scope (vs. just updating Interface fields). Also unconfirmed: Nautobot version and the shape of the incoming CDP data.

If the numbers are worth showing too (useful for tracking progress across rounds), put them on a collapsed line below the plain-language summary — never as the headline:

```
(Context 12/25, Task 18/25, Format 5/25, Constraints 8/25 — 43/100)
```

A person reading this live shouldn't have to do arithmetic or know the band system to understand what's missing. This applies even on the first pass — always state the gaps in plain language before asking anything.

## 3. Check what you can determine yourself before asking the user

Read the relevant files / grep the codebase / check project conventions first. Only unresolved gaps that require the user's input get asked about, and only if closing them would raise the score (i.e., materially change the output).

Distinguish **ambiguity** (information the user could supply that would resolve the gap) from **infeasibility** (a precondition that no amount of clarification fixes — e.g., the target project has no code yet, a required tool isn't installed). Infeasibility is a blocker to report, not a rubric gap to keep querying about; a low Context score in this case doesn't mean "ask more," it means "this can't proceed as stated."

## 4. Ask about the lowest-scoring dimensions, batched

Use `AskUserQuestion` to close the gaps identified in Step 1, following these rules:

- **Cap: 4 questions per round** — the tool's practical limit. If more than 4 real gaps remain, ask the top 4 now and cover the rest in a subsequent round; don't cram extras into one call.
- **Priority: biggest point gap first.** Ties don't need a tiebreak — batch tied dimensions together in the same round.
- **Skip anything Step 3 already flagged infeasible.** Don't draft a question about something no amount of clarification can fix.
- **Prefer concrete options with a recommended default** over open-ended questions — options teach the user the axes of variation instead of making them generate an answer from nothing.

## 5. Re-score after every round, but only report the delta

Re-score internally after each round (the numbers still drive Step 6's floor/threshold logic), but don't re-render the full gap summary from scratch — state what changed, in plain language: "Format and Constraints are clear now. Still open: which Nautobot version, and whether the remote device should be auto-created." Keep any numbers secondary/collapsed, same as Step 2.

No fixed cap on this user-clarification loop — the target is the threshold (see below), not a number of tries. Keep rounds going as long as each round is closing real gaps. (This is separate from the independent-verification loop in Step 7, which does have a 2-round cap.)

## 6. Threshold and override

- Default required score to proceed: **100/100**.
- **Per-dimension floor:** a high sum does not by itself meet the threshold — every dimension must also independently score **≥20**. A request can total 90+ overall and still fail this gate if one dimension (e.g. Task) sits at 6 while the others are maxed; don't let strong scores elsewhere compensate for one severe, unresolved gap.
- **Destructive/irreversible actions:** if the task involves an irreversible, destructive, or production-impacting action (deleting data, modifying production infrastructure, force-pushing, dropping tables, and the like), **Constraints must score the full 25** regardless of the sum or the floor above — this dimension is where "what must not happen" lives, and reduced rigor there is never acceptable no matter how mature the rest of the request is.
- **Explicit override** — the user directly lowers the bar or accepts the current score ("proceed anyway," "that's good enough," "use your judgment on the rest"): stop immediately, state the accepted score plainly (e.g., "Proceeding at 78/100 — Format and Constraints gaps accepted, not resolved"), skip Step 7 (nothing to independently verify against a gap the user already accepted), and go straight to Step 8.
- **Implicit override** — the user answers some questions in a round but leaves others unaddressed, or doesn't respond to a follow-up round at all: treat the unanswered items as an accepted lower score for those specific gaps only. State which dimensions remain below max because of this, then proceed as in the explicit case above. Don't re-ask the same question a second time.
- In either case, never silently relabel an accepted partial score as 100%, and never inflate scores to reach the threshold faster — if genuine ambiguity remains, the score reflects that, even after multiple rounds.

## 7. Independent verification (only when the self-assessed score hits 100/100)

A score you assigned yourself, in the same thread that did the clarifying, is not trustworthy on its own — you're motivated to see the gaps as closed because you just spent effort closing them. Before treating 100/100 as real, get a second, unbiased read:

- Use the `Agent` tool (a fresh agent, no shared context with this conversation) to independently re-score.
- Give it **only**: the original raw request, and the clarified spec (the 3-5 bullet restatement) — never your rubric table, your point values, or your reasoning. Seeing your scores would anchor it into agreeing with you instead of judging independently.
- Ask it to apply the identical rubric (paste the four dimension tables verbatim into the prompt) and return its own scorecard plus total, with no knowledge of what score is "expected."
- Re-scoring the bullets alone only anonymizes the score — it doesn't fact-check it. If the clarified spec relies on anything supposedly verified from the actual project (files read, conventions checked, existing code inspected), instruct the verifier to independently re-read those same files/grep the same codebase and reach its own conclusion, rather than taking the claim on faith. Only pass through items that are inherently unverifiable except by asking the user (a stated preference, a business decision) as accepted fact.
- Reconcile:
  - Independent score also 100/100 → confirmed, proceed to step 8.
  - Independent score lower → its gap findings are the real signal (a fresh reader isn't invested in your prior clarifying rounds). Surface exactly what it flagged, ask the user any follow-up question needed to close that specific gap, then re-run this verification step.
  - Cap at 2 independent-verification rounds. If disagreement persists after that, stop, report both scores and the specific unresolved gap to the user, and let them decide whether to accept it as an override (per step 6) rather than looping indefinitely.

## 8. Confirm in plain language, then execute

Don't show a final scorecard or point totals here — "100/100 — proceeding" reads as pass/fail gamification, not communication. State readiness in one plain line instead ("All clear — building it now," or "Independently double-checked — building it now" when Step 7 ran), then restate the clarified spec in 3-5 bullets — that's what actually does the communicating. Do the work in the same turn — no separate confirmation step, and no narrating the process that got you here (see the Goal section).
