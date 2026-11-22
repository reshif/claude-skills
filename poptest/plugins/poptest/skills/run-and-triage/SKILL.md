---
name: run-and-triage
description: Run a poptest suite against the real system, read the report, and triage every finding into product bug, wrong case/rule, or flaky, with reproduction rates and shrunk scripts; turn confirmed failures into regression cases. Use for "run the tests", "what failed", "why did this case fail", "is this flaky", "explain the report".
---

# Run and triage

CLI path: the `poptest` skill.

## Run

```
poptest validate                      # must say OK
poptest run                           # all cases
poptest run --only boundary clock     # by family or case id (prefix* allowed)
poptest run --population --budget 600 # cases plus simulated users
poptest run --target other.py:Class   # another build; also a URL or a target .json
```

Each run writes `runs/<name>/`: `events.jsonl` (everything that happened), `report.md` (for people), `report.json` (for tools). Exit code 1 means findings were raised.

After the conversations, the run does three things with the findings, and for a target that is restarted per case (http, cli) this takes longer than the run itself:

1. **Groups them by root cause.** Findings are one problem when they share the check, the action (tool and argument condition) and the steps that led to it (a no, a yes, a clock jump, another window, another user, an outside change, a backend failure). A case's own expectations (`expect:*`) join the failure they echo in the same conversation, and several rules firing on the same action or the same reply are one failure. So "153 findings" become the dozen problems they are; each problem lists the other checks that saw it ("also seen as") with counts, and the first line of every distinct example.
2. **Runs every failing conversation again** (twice by default) so each finding has its own reproduction count, then replays one example per problem 5 times.
3. **Shrinks the example** to the shortest script that still shows it, and replays the result before showing it.

```
poptest run --replays 0               # only run and group: no re-run, replay or shrinking (fastest)
poptest run --no-shrink               # re-run and replay, do not shrink
poptest run --reruns 0                # replay only the example of each problem
```
A long run prints a progress line every few seconds; with a tool time limit, use `--replays 0` first and `poptest replay` on the problems you want to dig into.

### The flake rule

A problem is only listed as found when it **comes back**: its example must show it in at least `min_hits` of the replays (default 2 of 5). Everything else goes under "Did not reproduce" in the report, is marked `[DID NOT REPRODUCE]` on the console, and is not counted in the headline. Inside a problem, the report says how many of its conversations came back when run again and names the ones that did not. The rule is declared in `poptest.json` and fixed before the run:

```json
"flake": {"min_hits": 2, "reruns": 2}
```

If the target is random **by specification** (a documented share of "please repeat" replies), do not rely on this rule to filter it: declare the noise replies (`connect-target`, section 4) so that those turns are resent and never become findings. The report then has a section "Replies declared as noise" with the measured rate and whether any such turn changed data.

## Read

Open `report.md`. Do not summarise from the console output. For any problem:

```
poptest show latest                 # every conversation: "FAIL  <id>   <- codes" or "ok    <id>"
poptest show latest --failing       # only the failing ones
poptest show latest <conversation>  # full transcript with every action and result (--full: untruncated results)
poptest replay latest <conversation> --code <problem> -n 10 --shrink
```

`report.json` has the same content for scripts: `problems` (one per root cause: `code`, `codes` with counts, `tool`, `action`, `trigger`, `conversations`, `examples`, `replay`, `rerun`, `flaky`), `by_conversation` (each failing conversation with its codes and problem ids) and the raw `findings`.

### How far a script is cut down

A shrunk script must still contain the cause. How much is cut depends on what the failure rests on:

| Failure | What may be cut | Why |
|---|---|---|
| built-in checks and rules (`unconfirmed_action`, `privacy_leak`, `rule:*`, ...) | anything, as long as the same check still fires | the check carries its own evidence |
| "must not happen" expectations (`expect:no_calls`, `expect:unchanged`, `expect:*_not_*`) | everything after the violation, and greetings / thanks / junk before the first step that matters | the expectation only means something together with the steps that make the action wrong, and no program can tell which message that is. So every message that says something, every no and yes, clock jump, outside change, backend failure, other window, other user and the whole set-up are kept. Cutting what follows the violation is always safe: what has happened stays happened |
| "did not happen" expectations (`expect:calls`, `expect:world`, `expect:*_contains`) | greetings / thanks / junk only, and only if every other exchange (replies and calls) stays exactly the same without them | deleting messages only makes the expected thing less likely, and a product whose bug is ignoring a message behaves the same without it |

"Greetings, thanks, junk" are the `say.hello`, `say.bye` and `junk` lists of the vocabulary; add the product's own filler in `vocab.json`. Expectation failures therefore shrink little, on purpose: for those, the case as written is usually the script to report. To get a shorter one, shrink the built-in check or rule that fired in the same conversation (`poptest replay <run> <conversation> --code unconfirmed_action --shrink`), which is cut freely and safely.

In every mode the shorter script must fail on **the same expectation entry**, and it is replayed before it is shown; if it does not fail again, the original script is kept. The report says under the script which mode was used.

`--export` saves a regression case holding only the one expectation entry that failed, after replaying it: **a script that passes on the expectation that defined the failure is refused** ("not exported: ...") instead of being saved. Still read every exported case once: for rules that count things across messages (three wrong answers, five pending items) a shorter script can fire the same rule for a legitimate reason.

## Triage every problem into one of four

1. **Product bug.** The shrunk script plainly shows the system doing what the spec forbids. Keep it: `poptest replay <run> <conversation> --shrink --export` saves it under `cases/regressions/` so it is tested forever. Report it with the script, the rate, and the spec sentence it breaks.
2. **Wrong case or rule.** The system behaved acceptably and the expectation or pattern was wrong (too broad a claim pattern, a guessed policy, an id that belongs to someone else). Fix the case or rule, rerun that family. Say what you changed. Never loosen a check only to get a pass: if you cannot point to the spec, ask the person.
3. **Unclear spec.** The script is right, the behaviour is defensible, the spec is silent. Put the question to the person with the script.
4. **Not reproducible.** Listed under "Did not reproduce". The failure depended on chance, on timing or on other users' activity. Rerun with `poptest replay <run> <conversation> -n 20`. A low but real rate on a serious problem (privacy, unconfirmed action) is still a bug: report the rate.

The report is already grouped by root cause; check the grouping rather than redo it. Two problems with the same headline and different "steps leading to it" may still be one bug in the product (say so), and one problem whose distinct examples read very differently may be two.

Lower-confidence signals (simulated users who did not get what they came for) need the transcript read every time: often the simulated user gave up reasonably, sometimes the system really lost the thread.

## Report to the person

Lead with the count of confirmed product bugs and the worst one. For each bug: one plain sentence, the shortest script (copy it from the report), how often it reproduces, why it matters. Then: cases or rules you corrected, questions about the spec, and what was not tested (families with no cases, checks that could not be evaluated, anything `connect-target` could not sandbox). State that counts describe this test set, not real-world frequency.

If nothing was found, say what that is worth: suggest `mutation-score` to see how many planted faults this suite would catch before anyone relies on a clean run.
