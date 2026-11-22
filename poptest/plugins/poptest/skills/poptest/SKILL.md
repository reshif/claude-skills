---
name: poptest
description: Test software that takes actions over time (an AI agent, chatbot, workflow or API with tools and state) against a fake world, with code checks on what it really did. Use for "test my agent/bot", "does it ever act without confirmation", "does it leak other users' data", "find multi-turn bugs", "is the new release worse", "how good are my tests". Entry point that routes to the setup, world, rules, cases, run, compare and mutation skills. Not for judging answer quality, opinions or single-turn prompts.
---

# poptest

poptest finds failures in systems that **do things** across several messages: refund, book, update, delete, approve, send. It works by owning the world the system acts on. Because the data is fake and ours, the true state is always known, and every check is code comparing what the system did and said with that truth.

## When NOT to use it

Say so plainly and suggest the better tool when the request is one of these:

- **Answer quality.** "Are the answers good, helpful, well written, on brand?" There is no true state to check against. Use an evaluation set with graded answers.
- **Opinions and taste.** Tone, persuasion, creativity. A code check cannot decide them.
- **Single-turn question answering.** One prompt in, one answer out, no tools, no state. A plain list of prompts with expected answers is cheaper and just as good.
- **No sandbox possible.** If the system's tools cannot be pointed at fake ones (see `connect-target`), poptest can only watch replies. Privacy and crash checks still work; action checks do not. Tell the person before starting.
- **Production.** Never point it at live customer data or real payment/email/booking backends. Sandbox or staging only.

Use it when at least one is true: the system calls tools that change data; it must ask before acting; it serves several users whose data must stay apart; behaviour depends on earlier messages, earlier sessions or the date.

## What the evidence says (shapes the workflow)

In a blind trial on a bot with 20 planted bugs, about 200 targeted cases written by an LLM found 12; a simulated population of users found 8. The harness (fake world, checks, replay, mutation scoring) is what made the cases effective. So:

1. **Written cases are the main tool.** Aim for 150 to 250, covering the failure-family checklist in `generate-cases`.
2. **Checks decide what can be seen.** Three of the five bugs the cases missed were gaps in the checks. Spend real effort in `write-rules`.
3. **Population mode is secondary.** It found one state bug the cases missed. Run it after the cases, with a modest budget.
4. **Measure the tests.** `mutation-score` plants faults and reports which kinds the suite is blind to.

## The CLI

Deterministic work is done by `poptest`, Python 3 standard library only. It lives at `bin/poptest` in this plugin (`../../bin/poptest` from this file; `${CLAUDE_PLUGIN_ROOT}/bin/poptest` where that is set). Resolve the absolute path once and call `python3 <path> ...` from the project folder. Every command has `--help`.

| Command | Does |
|---|---|
| `init [DIR] [--bare] [--example expense-agent]` | scaffolds a project: a runnable sample, empty files (`--bare`), or the worked example |
| `validate` | checks every file, starts the target once, counts cases per failure family; problems are plain `PROBLEM:` lines, never a traceback |
| `world [--entity E --where EXPR] [--user U]` | shows the generated sandbox data (you need real ids to write cases) |
| `say --user U [--hour H] [--full] "msg" +13h "msg"` | sends messages by hand, prints replies, actions and any check that fired; `+2d` / `+13h` / `+30m` between messages moves the clock |
| `run [--only ...] [--population --budget N] [--export] [--replays N] [--reruns N] [--no-shrink]` | runs, checks, groups findings by root cause, re-runs, replays, shrinks, writes `runs/<name>/report.md` and `report.json` |
| `show [RUN] [CONVERSATION] [--failing] [--full]` | lists a run's conversations (FAIL / ok), or prints one |
| `replay RUN CONVERSATION [-n 5] [--shrink] [--export]` | reproduction rate and shortest script for one failure |
| `compare --a A --b B` | release A against B with the rule in `poptest.json` |
| `mutate [--n 40] [--file src.py] [--approaches cases,population]` | detection power of the suite (python targets, and http/cli targets with Python source) |
| `personas`, `serve-tools` | preview simulated users; run the fake-tools server alone |

Exit codes: 0 clean, 1 problems found (or B worse than A), 2 a project file is wrong.

## Project files

`poptest.json` (config: `target`, `noise`, `flake`, `compare`, `unknown_users`, `mutate`), `world.json` (entities, records, generator, private fields, clock), `tools.json` + `tools.py` (fake tools), `rules.json` + optional `rules.py` (what must always hold), `cases/*.json`, `vocab.json`, `population.json`, `runs/`.

## Route by what the person asked

| They want | Skill |
|---|---|
| start from nothing, or "test my agent" | `connect-target`, then `build-world`, `write-rules`, `generate-cases`, `run-and-triage` in that order |
| "write the fake backend from our API docs" | `build-world` |
| "what should always be true" | `write-rules` |
| more or better cases | `generate-cases` |
| results, a failing case, a flaky failure | `run-and-triage` |
| "is the new version worse" | `compare-releases` |
| "can I trust these tests" | `mutation-score` |

For a first setup, tell the person the plan in five lines, then ask only what you cannot find in their repo or docs: how to reach the system, what it is allowed to do, and what must never happen.

## Ground rules

- Read the product's spec, API docs and code before writing anything. Every rule and case must trace to a sentence in them or to something the person said. If the spec is silent on a behaviour, ask, or leave the case out; do not invent policy.
- Run `validate` after every file you write and `say` to see real replies before writing rules that match reply text.
- A finding is a script plus a check plus a reproduction rate. Report it that way. Never summarise results from memory: read `report.md`.
- If the spec says the system answers some messages at random with a "please repeat" reply, declare it under `noise` in `poptest.json` (`connect-target`, section 4) before writing cases. Do not wrap the target to hide it.
- If the system confirms without a question mark, or one backend tool serves several kinds of action, set `question_patterns` and action entries with `tool` + `when` (`write-rules`) before the first run, or the confirmation check drowns the report.
- Counts are about this test set. Do not present them as how often real users will hit a problem.
