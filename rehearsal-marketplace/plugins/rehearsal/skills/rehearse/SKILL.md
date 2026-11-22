---
name: rehearse
description: Run a pre-mortem rehearsal on a request before the factory builds it — critics grounded in real tickets and incidents attack each variant, an analyst writes an evidence-backed outcome report, the human picks at a gate, and unhappy paths become acceptance tests. Use for big or risky requests, "rehearse this", "pre-mortem", "what could go wrong", "compare variant A vs B before building".
---

# Rehearse

A rehearsal answers one **outcome question** about a request ("Will admins adopt bulk export without a ticket spike?") by letting grounded critics attack each variant, then turning what they find into a decision and tests. It is scenario exploration, not forecasting: say so in the report.

## The CLI

Every stage writes through the `rehearse` CLI, which refuses invented evidence. It lives at `bin/rehearse.py` in this plugin (`../../bin/rehearse.py` from this file; `${CLAUDE_PLUGIN_ROOT}/bin/rehearse.py` where that is set). Resolve the absolute path once and call it as `python3 <path> ...` from the repo root. State goes in `./.rehearsal/`. `rehearse <cmd> --help` documents every flag.

## Flow

Create a task list with these steps, and tick them off.

1. **Cost guard.** `rehearse init` if `.rehearsal/` is missing. Then `rehearse should-run --tags <tags> --files N --services N [--irreversible]`. Tags: auth, payments, pii, migration, public-api, infra, data-model, perf, ui, integration. If it says no and the user did not insist, say so in one line and stop; suggest the normal factory path. Small changes don't need a rehearsal.
2. **Frame.** Settle with the user (one AskUserQuestion at most, skip if the request already says): the outcome question, 1–3 variants with one-line descriptions, and up to 3 what-ifs (e.g. "10x data size"). Then `rehearse new <slug> --request <file> --question "..." --variants A,B --variant-desc A="..." --what-if "..."`.
3. **Seed the world** — follow the `seed-world` skill.
4. **Cast** — follow the `cast` skill (at most 8 personas; the budget enforces it).
5. **Review arena** — follow the `review-arena` skill.
6. **Threat arena** — follow the `threat-arena` skill. Steps 5 and 6 are independent: launch their subagents in the same turn.
7. **Outcome report** — follow the `outcome-report` skill. Show the user the rendered `report.md` summary, verdicts and top risks.
8. **Gate** — the human decides. Ask with AskUserQuestion: approve a variant (optionally with required changes), revise (back to step 2 with a new variant or what-if), or kill. Record with `rehearse gate`. Never decide for them; in an unattended run, stop here with the report ready.
9. **Tests** — follow the `paths-to-tests` skill and hand the acceptance criteria to the factory's spec/build stage.
10. **Later:** after release, the `calibrate` skill compares predictions with reality. Tell the user this in one line at the end.

`rehearse status <run>` shows what is done and what is next at any point; use it to resume an interrupted run.

## Rules

- Critics only cite evidence that exists: fact ids (`F12`), earlier finding ids (`R3`), or `sarif:`/`file:`/`test:` refs. If a critic has no evidence, the finding is dropped, not reworded.
- Keep the user out of the plumbing: report outcomes, not CLI calls.
- Cheap models for crowds (the critic agents default to sonnet), the main session for the analyst.
- If a CLI call fails validation, fix the data and resend; never edit `.rehearsal/` files by hand to get around it.
