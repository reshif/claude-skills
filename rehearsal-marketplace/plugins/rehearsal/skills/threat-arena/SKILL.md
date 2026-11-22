---
name: threat-arena
description: Run the rehearsal's threat arena — adversary personas probe each variant with a STRIDE pass, and deterministic scanners (Semgrep, STRIDE GPT) run where installed; SARIF results become findings. Part of the rehearse flow.
---

# Threat arena

Adversaries attack the design; scanners attack the code. Scanner output is evidence, not opinion, so prefer it where it exists.

CLI: see the `rehearse` skill.

## 1. Adversary critique (parallel with the review arena)

For each persona with role `adversary`, launch an **adversary** subagent with the persona JSON, request, variants, what-ifs, facts (`rehearse world query --run <run>`) and the affected code paths from seed-world. It returns JSON lines of findings; save with `rehearse finding add <run> --arena threat --file -`.

## 2. Scanners (only if installed — check, don't install)

Check with `command -v semgrep` and `command -v stride-gpt`. Run what exists over the affected paths only, and send SARIF into the run. Use the variant the code belongs to: for a design not yet built, run against the current code and record under each variant that keeps that code path.

- **Semgrep:** `semgrep scan --config auto --sarif --output /tmp/semgrep.sarif <paths>` then `rehearse ingest-sarif <run> /tmp/semgrep.sarif --variant <V> --limit 25`
- **STRIDE GPT:** check `stride-gpt --help` for its current flags; if it can emit SARIF, ingest it the same way. If it only emits Markdown/JSON, read it and have the adversary agent turn each threat into a finding with `evidence: ["file:<report path>"]`.

If neither is installed, say so in one line in the report's open questions ("no static scan was run") and carry on.

## Done

One line to the user: threat findings per variant, and the worst one.
