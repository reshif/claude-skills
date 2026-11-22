---
name: backtest
description: Test whether rehearsals are worth it by replaying past features — run a rehearsal with the world frozen at a date before the feature shipped, then score its predictions against what is already known to have happened. Use for "backtest the rehearsal", "would this have caught X", "is the rehearsal worth it".
---

# Backtest

A backtest answers the question that matters before you invest further: **would a rehearsal have caught the problems we actually had?** Do 5–10 past features before trusting the rehearsal on real work.

CLI: see the `rehearse` skill.

1. **Pick features** with the user: shipped 1–12 months ago, with known after-effects (incidents, ticket spikes, rework, security fixes) — and a few that went fine, so false alarms show up too.
2. **Seed the world with dates.** Follow `seed-world`, giving every fact its true `--valid-from`. Facts about what happened after the release must carry dates after the cutoff. This is what blocks hindsight.
3. **Run with a cutoff:** `rehearse new <slug> --request <original spec> --question "..." --as-of <day before the release>`. The CLI then refuses personas and findings that cite facts not yet true on that date.
4. **Rehearse blind.** Run cast, review-arena, threat-arena and outcome-report as normal. Critics get only `rehearse world query --run <run>` output, never post-release facts or your knowledge of what happened. Don't hint.
5. **Gate as it was:** record the variant that was actually built (`rehearse gate <run> --decision approve --variant <V> --note backtest`).
6. **Score:** follow `calibrate` steps 3–5 using what is known to have happened.
7. **Decide with the user** after the batch, from `rehearse calibrate score`:
   - recall of real problems ≥ ~50% with tolerable false alarms → use the rehearsal on big/risky requests;
   - most hits come from the review and threat arenas → that's the right scope; don't add simulated-user crowds;
   - recall is low → compare against one well-prompted single critic before investing more.
