---
name: review-arena
description: Run the rehearsal's review arena — every non-adversary persona critiques every variant in parallel, then a short debate round where they respond to each other — and record the findings. Part of the rehearse flow.
---

# Review arena

Stakeholders, users and services attack each variant like a design-review thread. Two rounds at most (the budget enforces it).

CLI: see the `rehearse` skill.

## Round 1 — independent critique (parallel)

For each persona with role `user`, `stakeholder` or `service`, launch one **persona-critic** subagent. Launch them all in one turn so they run in parallel. Give each, in its prompt:

- the persona JSON (`rehearse cast list <run>`),
- the request (`.rehearsal/runs/<run>/request.md`), the outcome question, and every variant with its description,
- the what-ifs from `run.json`,
- the facts: output of `rehearse world query --run <run>`,
- the arena name `review` and round `1`.

Each critic returns only JSON lines of findings. Collect them and save in one call per critic:
`rehearse finding add <run> --arena review --file -`

If the CLI rejects a line (unknown fact, missing field), drop that line and keep the rest; don't rewrite a critic's claim to make it pass.

## Round 2 — debate (parallel)

Show the round-1 findings (`rehearse finding list <run> --arena review`) to each critic again, with `round 2`. They may agree, rebut or escalate another persona's finding, citing its id (`R4`) as evidence, and add anything new the others made them see. Ask each critic in round 2 to look especially for **conflicts**: places where another persona's likely fix would break this persona's goals. In testing, these conflicts were the most useful output of the whole rehearsal, and round 1 didn't surface them. If budget forces a choice, run round 2 for the personas whose goals pull against each other most (e.g. security and the main user persona). Skip round 2 when round 1 produced fewer than 4 findings.

## Done

Give the user one line: findings per variant, and the single sharpest objection.
