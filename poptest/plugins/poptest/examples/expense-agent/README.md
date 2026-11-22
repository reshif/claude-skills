# Worked example: Expenso, an expense assistant

A complete poptest project for a small agent that adds, submits, deletes and approves expenses. Read it next to the skills: every file here is what the skills ask Claude to write for your system.

| File | What it is |
|---|---|
| `docs/SPEC.md` | the product spec everything else is derived from |
| `target/agent.py` | the system under test (release 1, correct) |
| `target/agent_v2.py` | release 2 with five planted regressions |
| `target/http_server.py`, `target/cli_bot.py`, `target/remote_tools.py` | the same agent as an HTTP service and as a command-line process, calling its backend over HTTP |
| `target-http.json`, `target-cli.json` | target configs for those (`poptest run --target target-http.json`) |
| `world.json` | users (private bank account and phone), expenses (owner, details, private note), fixtures on both sides of the 60-day and 500.00 limits, 40 generated employees |
| `tools.json`, `tools.py` | the fake backend, permissive like the real one |
| `rules.json`, `rules.py` | actions needing a yes, claim wording, stated facts, policy invariants |
| `cases/` | 89 cases in 15 failure families |
| `population.json`, `vocab.json` | simulated users' goals and extra vocabulary |

```bash
poptest run                                                   # clean
poptest run --target target/agent_v2.py:ExpenseAgent          # finds the regressions
poptest run --target target-http.json --only happy_path       # same agent over HTTP
poptest compare --a target/agent.py:ExpenseAgent --b target/agent_v2.py:ExpenseAgent
poptest mutate --n 40
poptest run --population --budget 600
```

The five regressions in release 2 and what catches them: the 60-day window off by one (`rule:submit-window`, boundary and clock cases); "please don't" read as "please do" (`unconfirmed_action`, negated-phrasing cases); status shown for anyone's expense (`record_detail_leak`); pending actions kept per user instead of per chat window (`unconfirmed_action`, concurrent-session cases); the 500.00 limit loosened (`rule:submit-limit`).
