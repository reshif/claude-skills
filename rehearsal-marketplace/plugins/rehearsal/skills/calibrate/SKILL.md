---
name: calibrate
description: After a rehearsed change has been released, record which predictions came true and which real problems were missed, then score personas and arenas so future rehearsals trust the right critics. Use for "calibrate", "how did the rehearsal do", "check predictions vs reality".
---

# Calibrate

This is what makes the rehearsal worth trusting over time. Run it 2–4 weeks after a rehearsed change ships, or on a backtest run.

CLI: see the `rehearse` skill.

1. **Find the run.** `rehearse list`, then `rehearse status <run>`; read `report.json` for its predictions.
2. **Check reality** for the approved variant's predictions, using the same sources as seed-world: tickets, incidents, analytics, PR reviews and bug reports since the release. Use connected tools; otherwise ask the user.
3. **Record each prediction you can judge:**
   `rehearse calibrate outcome <run> P2 --occurred yes --evidence SUP-120`
   `--occurred no` when the window passed and it did not happen. Leave unjudgeable ones out rather than guess.
4. **Record misses** — real problems the rehearsal didn't predict — with the role that should have caught them:
   `rehearse calibrate miss <run> --statement "CSV breaks on non-Latin names" --severity medium --role user`
5. **Score:** `rehearse calibrate score` (all runs) updates `.rehearsal/scores.json`: hits, false alarms, misses, Brier score (lower is better), precision and recall overall and by arena, role and persona, plus weights the `cast` skill applies next time. Roles need 3+ judged predictions before their weight moves.
6. **Feed the world:** add what actually happened as facts (`rehearse world add-fact ... --source incident:...`) so the next rehearsal in this area starts smarter.

Tell the user in plain words: how many predictions came true, what was missed, which critics earned trust and which lost it.
