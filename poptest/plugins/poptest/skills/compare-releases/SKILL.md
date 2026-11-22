---
name: compare-releases
description: Compare two releases of a system (old vs new build, prompt A vs prompt B, model swap) on exactly the same poptest cases or simulated users, with repetitions, a decision rule fixed before the run, and an A-versus-A noise floor. Use for "is the new version worse", "did this change break anything", "regression check before release", "compare A and B".
---

# Compare releases

Systems built on language models do not answer the same way twice, so "B failed a case A passed" proves nothing on its own. This procedure makes the comparison fair. CLI path: the `poptest` skill.

## 1. Fix the rule before looking at anything

In `poptest.json`:

```json
"compare": {"rule": {"reps": 3, "min_b": 2, "max_a": 0}}
```

Meaning: every conversation is run `reps` times on each side. A problem in a conversation counts as **new in B** when it shows in at least `min_b` of B's runs and at most `max_a` of A's runs. The command refuses to run without a declared rule, and writes the rule into the result. Agree it with the person first; do not change it after seeing results. For a flaky system raise `reps` (5, with `min_b` 3).

If the system is random **by specification** (a documented share of "please repeat" replies), declare those replies as noise first (`connect-target`, section 4). Otherwise a release compared with itself already "differs", raising `reps` does not help (a target that seeds its own randomness repeats the same glitch on every repetition), and the fixed/new lists fill with glitch victims. With the declaration the noise turns are resent on both sides and the noise floor returns to zero. Each repetition restarts the target; poptest does not seed the target's own random numbers.

## 2. Name the two releases

Each side is one of: `file.py:Class` (python target), a URL (http target), or a `.json` file holding a full target config (use this for different start commands, environment variables, prompts or model names).

## 3. Run

```
poptest compare --a old/agent.py:Agent --b new/agent.py:Agent
poptest compare --a target-old.json --b target-new.json --population --budget 600
```

The same cases, the same simulated users, the same seeded world go to both. A is run twice: the second run is compared with the first by the same rule. Whatever that reports is the **noise floor**. Output: `runs/<name>/compare.md` and `compare.json`. Exit code 1 when B is worse.

## 4. Read the result

- **New problems in B above the noise floor**: B is worse. Each row names a conversation and a problem; use `poptest run --target <B> --only <conversation>` then `run-and-triage` to get the shrunk script.
- **At or below the noise floor**: no evidence of a change at this number of repetitions. Say exactly that, not "B is fine".
- **Fixed in B**: problems A has and B does not, by the same rule in the other direction. In every table and in `compare.json`, `a_hits` is the number of A runs that showed the problem and `b_hits` the number of B runs (so a fixed row reads `a_hits: 3, b_hits: 0`).
- A noise floor above zero means the suite or the system is unstable for those conversations: mention them, and consider more repetitions.

Tell the person the rule, the three numbers (new, fixed, noise), the verdict in the report's words, and the top regressions as scripts. Never quote the rates as real-world failure rates: they are only meaningful as this paired comparison.
