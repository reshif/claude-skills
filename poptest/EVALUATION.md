# poptest: evaluation results

Four rounds of blind testing. Bugs were planted by independent agents, and testers never saw the answer key.

| Round | Setup | Result |
|---|---|---|
| 1 | v0 harness, toy shop bot, 20 bugs; simulated users vs an LLM-written test suite at equal spend | Simulated users 8/20, LLM-written cases 12/20. The harness (fake world, checks, replay) was the valuable part. |
| 2 | Plugin v1.0, booking bot, 12 buggy releases with a known-good version available | No plugin, compare against the good version: 12/12 in about 5 min. Plugin: 11/12 (Sonnet) and 10/12 (Opus) in about 16 min. |
| 3 | Plugin v1.0, 3 products (transfers, helpdesk, warehouse), first release, source readable | Plugin 24/24 for Sonnet, Fable and Opus. No plugin 22/24 in about 1 min by reading the code. |
| 4 | Plugin v1.1, 3 products (subscription, airline, coworking), compiled black box | Sonnet 21/24, Fable 17/24, Opus 22/24 (10-15 min each). No plugin 20/24 (about 2 min each). |

## Takeaways
- On black-box targets the plugin adds 1-2 hard bugs out of 24: two windows at once, stale state at confirmation, and the wrong record targeted. The cost is 5-8x the effort, and the result depends on the tester (one run found only 2/8).
- Most of the value comes from the failure-family checklist and replay, not the heavy harness.
- Open issues reported in v1.1: varied confirmation wording needs hand-written patterns, false claims fire on negations, fake tools can't see the calling user, nested records need hand-written privacy rules, and reports group findings by check rather than by bug.
