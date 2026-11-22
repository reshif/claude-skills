# poptest: test software that takes actions over time

AI agents, chatbots, workflows and APIs that **do things** (refund, book, approve, delete, send) fail in ways a list of prompts cannot catch: they act without a yes, show one user another user's data, forget what was said two messages ago, or get a date limit wrong by a day. poptest tests them against a fake world it controls, so every check is code comparing what the system did with the true state.

```
spec / API docs ─► Claude writes: fake world, fake tools, rules, 150-250 cases
                                        │
   cases / simulated users ─► driver ─► REAL system ─► fake tools ─► sandbox world
                                        │                               │
                             event log (JSONL) ◄────────────────────────┘
                                        │
        checks (code, true state) ─► replay N times ─► shrink ─► report ─► regression cases
                                        │
                  compare releases (declared rule, noise floor)   mutation score (test the tests)
```

Claude Code is the only model involved. Anything needing judgement (the fake backend, the rules, the cases, the users' vocabulary) is written by Claude following the plugin's skills; everything deterministic is done by a Python standard-library CLI.

## Install

```bash
claude plugin marketplace add /path/to/poptest-plugin
claude plugin install poptest@poptest-marketplace
```
Or inside Claude Code: `/plugin marketplace add …`, then `/plugin install poptest@poptest-marketplace`, then restart. Requirement: Python 3.10 or newer (developed on 3.13). No packages, no network, no model API key.

## Use

```
/poptest:poptest test the support agent in ./agent (spec in docs/spec.md, API in docs/openapi.yaml)
/poptest:poptest-setup ./agent docs/spec.md
/poptest:poptest-cases
/poptest:poptest-run
/poptest:poptest-compare old/agent.py:Agent new/agent.py:Agent
/poptest:poptest-mutate --n 40
```

New in 1.1 (see [`CHANGELOG.md`](CHANGELOG.md)): targets that are random by spec (declared noise replies, a flake rule), confirmation detection by pattern and per action, shrinking that never loses the cause, reports grouped by root cause, mutation testing for HTTP and CLI targets.

Or just ask: "test my agent for actions taken without confirmation", "is the new release worse than the old one", "how good are these tests".

The 10-minute quickstart, the file formats and the CLI reference are in [`plugins/poptest/README.md`](plugins/poptest/README.md). A complete worked example (an expense assistant with 89 cases and a second release with five planted regressions) is in [`plugins/poptest/examples/expense-agent`](plugins/poptest/examples/expense-agent).

## When not to use it

Answer quality, opinions and tone, and single-turn question answering: there is no true state to check against, and a graded evaluation set is the right tool. Systems whose tools cannot be pointed at fakes get reply-only checks. Never run it against production data.

## Tests

```bash
cd plugins/poptest && python3 -m unittest discover -s tests
```
