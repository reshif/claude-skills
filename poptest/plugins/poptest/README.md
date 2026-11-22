# poptest

A testing harness for software that takes actions over time: a fake world it controls, a driver that talks to the **real** system under test, code checks against the true state, replay and shrinking of failures to short scripts, release comparison, and mutation testing of the tests themselves ("detection power").

Python 3 standard library only. No model API: Claude Code writes the judgement parts (fake tools, rules, cases, vocabulary) by following the skills; the `poptest` CLI does the deterministic parts.

## 10-minute quickstart

Put `bin/` on your PATH or call `python3 /path/to/plugins/poptest/bin/poptest`.

**Minute 0-2: see it work on the worked example.**

```bash
poptest init demo --example expense-agent
cd demo
poptest validate          # 45 users, 135 expenses, 8 tools, 89 cases in 15 failure families
poptest run               # 89 conversations, 0 findings: release 1 is clean
```

**Minute 2-5: run the release with regressions and read the report.**

```bash
poptest run --target target/agent_v2.py:ExpenseAgent --name v2
less runs/v2/report.md
```

The report lists each problem in plain words (for example "An action was taken without a clear yes from the user"), how many conversations hit it, how often it came back when the same messages were replayed, the shortest script that shows it, and why it matters:

```
User: submit EX-9001
System: Shall I submit EX-9001 (Cafe Uno, $23.50) for approval?
User: please don't
    (the system did: submit_expense(expense_id=EX-9001) -> {"ok": true})
System: Done. EX-9001 has been submitted for approval.
```

**Minute 5-7: look closer, keep the failure as a permanent case.**

```bash
poptest show v2                                  # every conversation, failing ones marked
poptest replay v2 negated-submit-2 --target target/agent_v2.py:ExpenseAgent -n 10 --shrink --export
poptest say --user E01 "submit EX-9003" "yes"    # talk to the system by hand
```

**Minute 7-9: compare the releases, then test the tests.**

```bash
poptest compare --a target/agent.py:ExpenseAgent --b target/agent_v2.py:ExpenseAgent
poptest mutate --n 40                            # plant 40 faults; how many does the suite catch?
poptest run --population --budget 600            # add simulated users on one shared world
```

**Minute 9-10: start on your own system.**

```bash
poptest init my-tests        # a small runnable sample (a task list) to copy from
poptest init my-tests --bare # or: empty files, nothing to clean up
```
Then in Claude Code: `/poptest:poptest-setup <your system and its spec>`. The skills walk through connecting the target, building the world and fake tools from your API docs, writing the rules, and generating 150-250 cases.

## How it fits together

| Piece | File | Who writes it |
|---|---|---|
| Connection to the real system | `poptest.json` → `target` | Claude (`connect-target`) |
| Sandbox world: entities, fixture records, seeded generator, private fields, clock | `world.json` | Claude (`build-world`) |
| Fake tools: declarations + small Python handlers | `tools.json`, `tools.py` | Claude, from your API docs |
| Rules: actions needing a yes, claims, stated facts, invariants | `rules.json`, optional `rules.py` | Claude (`write-rules`) |
| Cases: scripted, multi-session, with expectations | `cases/*.json` | Claude (`generate-cases`) |
| How users say yes and no; simulated users' goals | `vocab.json`, `population.json` | Claude, extendable |
| Runs: event log, report, shrunk failures | `runs/<name>/` | the CLI |

Nothing about any product is built in. The expense example, the `init` template (a task list) and the test fixture (a ticket desk) are three different worlds on the same code.

### Adapters

- **python**: `"entry": "file.py:Class"`; `Class(tools)` with `handle(user, session, text)`. Fake tools are `tools.name(arg=...)`.
- **http**: a chat endpoint. poptest starts a fake-tools HTTP server and passes its address in `POPTEST_TOOLS_URL` (or in any variable: `"env": {"BACKEND_URL": "{tools_url}"}`); the target's backend URL is set to it. Optionally starts and restarts the target process: the start command runs in its own process group and the whole group is stopped; ready means the readiness URL answers below 500; `"port"`, `"tools_port"` and `"port_range"` fix or confine the ports; `"attribution_headers": {"user": "X-User", "session": "X-Session"}` maps the product's own identity headers on backend calls.
- **cli**: a process on stdin/stdout, JSON lines or plain text.

Fake tools answer errors by raising `ToolError("unknown user", status=404)` (`from poptest.tools import ToolError`): the status code over HTTP, an exception with `.status` in-process. Any other exception in a handler is a 500.

### Targets that are random by specification

```json
"noise": {"replies": ["^Sorry, could you repeat that\\?$"], "max_resends": 3}
```
A turn answered only with a declared noise reply is recorded, the message is sent again, and only the real answer is checked. A noise turn that changed data is the finding `noise_side_effect`. The report gives the measured rate. No wrapper, and the branch stays under test.

### The clock

One injected clock: `world.day`, `world.date()`, `world.now()` (`2026-03-02T09:00`), `world.hour()`, `world.minute()`, `world.time()`, `world.weekday()`. It starts at 09:00 unless `"clock": {"start_hour": 22}` (or `"start_time": "22:30"`) says otherwise, and day and date roll over together at midnight. Cases use `{"advance": {"hours": 13}}` and `"clock": {"hour": 22}`.

All three produce the same event log (`events.jsonl`): `run_start, conv_start, world_patch, session_start, user_msg, bot_msg, tool_call, target_error, clock, session_end, conv_end, run_end`. Every `tool_call` carries the arguments, the result, the acting user, the referenced records as they were before the call, and the exact field changes. Checks need only this file and the project files.

### Built-in checks

| Code | Meaning |
|---|---|
| `crash` | the target raised, timed out or returned an error |
| `privacy_leak:<entity>.<field>` | a private field value of someone else's record appeared in a reply |
| `record_detail_leak:<entity>` | a reply named someone else's record and showed its details |
| `unconfirmed_action:<action>` | an action needing a yes ran without a clear yes in that session (also: a no since the question, a yes in another window, two actions on one yes) |
| `confirm_mismatch:<action>` | the question named one thing, the action was done to another |
| `false_claim:<action>` | a reply said it was done; no such call succeeded |
| `noise_side_effect:<tool>` | a turn answered with a declared noise reply changed data |
| `wrong_user_change:<tool>` | a call changed a record owned by a different user |
| `wrong_user_access:<tool>` | a call used another user's id where the caller's own is required |
| `wrong_fact:<id>` | a stated number, date, status or value differs from the true state |
| `rule:<id>` | one of your invariants (on a call, on a data change, on a reply, at the end) |
| `expect:<kind>` | a case's expectation did not hold |
| `goal_not_met:<goal>` | a simulated user did not get a legitimate task done (lower confidence) |

An action is a tool, or one kind of use of a tool: `"close_ticket": {"tool": "update_ticket", "when": "args['fields'].get('status') == 'closed'", "needs_confirmation": true}`. What counts as the confirmation question is configurable (`"question_patterns": ["reply yes to confirm"]`; default: a reply with `?`). `must_mention` compares values as they are written: `{"arg": "amount_minor", "minor_units": 2}` expects `19.99` for `1999`, `{"arg": "to", "format": "<expression>"}` any text, and the `100` inside `SKU-100` is not a quantity of 100.

### Cases

Steps in order; several sessions open at once; other users; clock jumps; outside changes to the world:

```json
{"id": "yes-in-other-window", "family": "concurrent_sessions", "user": "E01",
 "steps": [{"session": "a", "say": "submit EX-9001"}, {"session": "b", "say": "yes"}],
 "expect": {"no_calls": ["submit_expense"], "unchanged": ["expenses"]}}
```

Also: `{"say": "...", "expect": {...}}` for one step's own expectation, `{"fail": {"tool": "x", "error": "timeout"}}` for a backend outage, `"unknown_user": true` for a user the backend does not know, `"clock": {"hour": 22}` to start at a time of day.

`poptest validate` counts cases per failure family: happy_path, boundary, mind_change, negated_phrasing, wrong_id, split_messages, topic_switch, cross_user, cross_session, concurrent_sessions, clock, permissions, record_detail_leak, messy_input, repeat_action.

### Population mode (secondary)

Personas are records with traits from a pairwise covering design. A two-stage simulator decides a structured move, then code makes the text messy from the vocabulary pack. A discrete-event scheduler interleaves all users on one world and one target instance; later rounds spend the message budget on personas whose conversations took paths not seen before.

### Replay, shrink, export

`poptest replay RUN CONVERSATION -n 10 --shrink --export`: reproduction rate, the shortest script, and the result saved under `cases/regressions/`. Replay rebuilds the world as it stood when the conversation began, from the log alone.

Shrinking never shrinks away the cause. Built-in checks and rules are shrunk freely (delta debugging over messages and set-up), because the check carries its own evidence. A "must not happen" expectation (`expect:no_calls`, `expect:unchanged`, ...) keeps every message that says something, every no and yes, clock jump, outside change, other window and the set-up, and loses only greetings before the first step that matters and whatever came after the violation. A "did not happen" expectation (`expect:calls`, ...) loses only greetings, thanks and junk, and only if every other exchange stays exactly the same without them. The shorter script must fail on the same expectation entry, is replayed before it is shown, and `--export` refuses to save a script that passes.

### Reports

Findings are grouped by root cause: same check, same action, same steps leading to it (a no, a yes, a clock jump, another window, another user). A case's own expectations and other rules that saw the same failure are listed under it with counts ("also seen as"), with the first line of every distinct example. Every custom rule has its own headline (`title`/`message` in rules.json; `title=` or the `RULES` table in rules.py). Every failing conversation is run again and each problem's example replayed; a problem that does not come back (`"flake": {"min_hits": 2, "reruns": 2}`) is listed under "Did not reproduce" and not counted.

### Compare and mutate

`poptest compare --a A --b B` runs the same material on both with repetitions and applies the rule declared in `poptest.json` (`"compare": {"rule": {"reps": 3, "min_b": 2, "max_a": 0}}`); A is also compared with itself for a noise floor. `poptest mutate` plants AST faults in a Python target and reports detection power per approach and the faults nobody caught. For http and cli targets whose source is Python, `--file service.py` copies the folder, swaps in the faulty file and launches it through the same start command. A target with no Python source cannot be mutated.

## CLI reference

```
poptest init [DIR] [--bare | --example NAME] [--force]
poptest validate [--no-target] [--target T]
poptest world [--entity E] [--where EXPR] [--user U] [--limit N] [--json]
poptest say --user U [--days-later N] [--hour H] [--full] [--target T] MESSAGE...   (+2d / +13h / +30m = clock jump)
poptest run [--cases PATH...] [--only ID|FAMILY...] [--population | --population-only] [--budget N]
            [--replays N] [--reruns N] [--no-shrink] [--export] [--target T] [--name NAME]
poptest show [RUN] [CONVERSATION] [--failing] [--full]
poptest replay RUN CONVERSATION [--code C] [-n N] [--shrink] [--export] [--target T]
poptest compare --a A --b B [--only ...] [--population] [--budget N] [--reps N]
poptest mutate [--file F] [--n N] [--seed S] [--reps N] [--approaches cases,population] [--jobs N] [-v]
poptest personas [--limit N] [--out FILE]
poptest serve-tools [--port P] [--user U]
```

Targets (`T`, `A`, `B`): `file.py:Class`, a URL, or a `.json` target config. Exit codes: 0 clean, 1 problems found or B worse, 2 a project file is wrong. Errors are one plain line (`poptest: ...` or `PROBLEM: ...`); `POPTEST_DEBUG=1` shows a traceback.

## When not to use it

- **Answer quality, helpfulness, tone, opinions**: no true state to compare with. Use a graded evaluation set.
- **Single-turn question answering** with no tools and no state: a prompt list is cheaper and as good.
- **Systems whose tools cannot be redirected** to the fake server: only reply-based checks (privacy, crash, stated facts) work.
- **Production**: sandbox or staging only.

## Known limits

- The simulated users' decisions are a seeded code policy, not a language model, and their goals and cue patterns are written per project. Their realism is unmeasured. Treat `goal_not_met` as a prompt to read the conversation.
- Counts and rates describe the test set. They are meaningful as a comparison between releases, not as a forecast.
- "The user typed it first" suppresses leak findings for that value in that conversation, so a leak the user could already name is not reported.
- Confirmation is judged from text: the system's question must match the configured `question_patterns` (default: contain `?`). Products that confirm with buttons need the adapter to render the button press as a message.
- Replay restarts the target, so a failure that depends on what other conversations left inside the target's own memory may not reproduce; the reproduction rate shows this.
- Shrinking of expectation failures is deliberately conservative (it removes little). Shrinking of rule findings is free, and for rules that count things across messages a shorter script can fire the same rule for a legitimate reason: read an exported regression case once.
- Grouping by root cause is by signature (check, action, steps leading to it). One product bug reached by two different paths shows as two problems.
- Mutation testing covers small faults in one Python file. It needs Python source it can copy and a target it starts itself, and says nothing about prompt or model changes. Per-message time limits for in-process targets use a POSIX timer.
- Messages are sent one at a time: real concurrency (a missing lock) is invisible. Two users cannot share one session id.
- Rule expressions and `rules.py` are your own code and run unsandboxed; do not load a project you do not trust.
- No browser adapter, no LLM judge, no attacker search.

## Tests

```bash
python3 -m unittest discover -s tests        # about 145 tests, under two minutes
```

## What changed in 1.1

See [`CHANGELOG.md`](../../CHANGELOG.md). In short: noise replies and a flake rule, configurable confirmation detection and per-action requirements, shrinking that keeps the cause, reports grouped by root cause, `init --bare`, a `validate` that never shows a traceback, a consistent clock, and mutation testing for http and cli targets.
