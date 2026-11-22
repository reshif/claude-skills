---
name: paths-to-tests
description: After the human approves a variant at the rehearsal gate, turn its unhappy paths, risks and defects into Gherkin scenarios and an acceptance checklist for the factory's spec and build stages. Part of the rehearse flow.
---

# Paths to tests

CLI: see the `rehearse` skill.

1. Confirm the gate: `rehearse status <run>` shows `gate.decision == approve`. If not, stop — the human hasn't approved a variant.
2. `rehearse tests gen <run>` writes, in `.rehearsal/runs/<run>/tests/`:
   - `rehearsed.feature` — one scenario per qualifying prediction (unhappy paths, risks, defects with likelihood ≥ 0.3, plus every high/critical), tagged with its prediction id;
   - `acceptance.md` — the same as a checklist with the evidence trail, plus any changes the gate required.
3. Improve the scenarios where the generated Given/When is vague: read the prediction and its findings and write concrete steps. Keep the `@P#` tags so calibration can trace them.
4. Hand off to the factory: copy `acceptance.md` into the spec for the change (or attach it to the factory's intake), and put `rehearsed.feature` where the repo keeps acceptance or e2e specs. If the repo has no Gherkin runner, the factory translates each scenario into its native test framework; the tags become test names or comments.

Tell the user how many scenarios came out, and where the files went.
