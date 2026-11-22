# Changelog

## 1.1.0

Driven by feedback from eleven independent first-time users on four products. Every item below has a regression test in `plugins/poptest/tests/test_v11.py`.

### 1. Targets that are random by specification

- **Noise replies.** `poptest.json`: `"noise": {"replies": ["^Sorry, could you repeat that\\?$"], "max_resends": 3}`. A turn answered only with a declared noise reply is recorded (`bot_msg` with `noise`, a `noise` event, `user_msg` with `resend`), the message is sent again, and only the real answer takes part in checks, expectations and what a simulated user sees. No wrapper around the target is needed and the branch stays under test.
- **No side effects, checked.** A noise turn that changed data is the new finding `noise_side_effect:<tool>`.
- A reply that still matches after `max_resends` is treated as the system's real answer.
- The report states the measured noise rate and how many noise turns called the backend or changed data.
- **Flake rule.** `"flake": {"min_hits": 2, "reruns": 2}`: every failing conversation is run again so each finding has its own reproduction count, the example of each problem is replayed, and a problem that does not come back is listed under "Did not reproduce" instead of in the headline. The example shown is one that reproduces. New `run --reruns N`.

### 2. Confirmation checks

- **Configurable detection.** `"question_patterns"` (regular expressions) on an action, or once under `"confirmation"` in rules.json. A `?` is only required when no pattern is set. Simulated users recognise the same patterns.
- **Requirements per action, not per tool.** `"close_ticket": {"tool": "update_ticket", "when": "args['fields'].get('status') == 'closed'", "needs_confirmation": true, ...}`. Findings and false-claim checks are per action.
- **Formatted values in `must_mention`.** `{"arg": "amount_minor", "minor_units": 2}` (1999 must read 19.99), `{"arg": ..., "format": "<expression>"}`, `{"arg": "fields.status"}` for values inside object arguments.
- **Ids inside other tokens.** The `100` in `SKU-100`, `1,100` or `100.50` no longer counts as a mention of 100; other arguments' values are blanked out of the question first.
- The finding now quotes the earlier message that was read as a no. `expect.calls` arguments match partially inside object arguments.

### 3. Shrinking

- Three modes by kind of failure. Checks and rules: free delta debugging as before. "Must not happen" expectations: every message that says something, every no and yes, clock jump, outside change, backend failure, other window, other user and the whole set-up are kept; only what followed the violation (provably safe) and greetings before the first step that matters are cut. "Did not happen" expectations (`expect:calls`, `expect:world`, `expect:*_contains`) are now shrunk too, as far as is safe: greetings, thanks and junk go, and only if every other exchange stays identical without them. (Filler is the vocabulary's `say.hello`, `say.bye` and `junk`.)
- A shrunk script must fail on the same expectation entry (`expect_key`), and is replayed before it is shown; otherwise the original is kept.
- `--export` saves only the expectation entry that failed, replays the case first, and **refuses to save a script that passes** on the expectation or check that defined the failure.

### 4. Reports

- Findings are grouped by root cause: same check, same tool and action, same steps leading to it. Expectations and other rules that saw the same failure are folded in with per-check counts; every distinct example's first line is listed.
- Every custom rule has its own headline: `title`/`message` in rules.json, `ctx.fail(..., title=)` or a `RULES` table in rules.py, else the rule id in words. "A rule of the product was broken" is gone.
- `report.json` gains `by_conversation`, and per problem `codes`, `tool`, `action`, `trigger`, `examples`, `rerun`, `flaky`. The console summary shows the grouping; `show` marks conversations `FAIL` / `ok` and has `--failing`.

### 5. Setup and documentation

- `validate` never shows a traceback: every part is checked on its own and reports `PROBLEM:` lines (leftover template goals, unknown entities and tools, bad patterns, bad shapes). All commands turn unexpected errors into one line (`POPTEST_DEBUG=1` for the traceback).
- `init` says which files are sample content; `init --bare` creates empty files. An empty `population.json` is a note, not a problem. Unknown expectation keys are reported.
- **Clock.** Day number and date now roll over together at midnight of the injected clock (1.0: 24 hours after the start). New `world.hour()`, `minute()`, `time()`, `weekday()`, `set_time()`; `"clock": {"start_hour": 22}` / `"start_time"`; case `"clock": {"hour": 22}`; `say --hour` and `+13h` jumps; `/clock` returns hour and minute. Documented.
- **Errors.** `ToolError(message, status=404)`; the status is used over HTTP and available in-process. Other exceptions in a handler are now a 500 (1.0: 400). `"ok_from_result": false` for tools whose `{"ok": false}` is an ordinary answer. Case step `{"fail": {...}}` injects backend failures.
- **rules.py.** The `ctx` object is documented field by field; new `ctx.session_messages`, `session_replies`, `session_user_msgs`, `said`, `stance()`, `error`, `status`. An exception in a hook is a warning with a line number, no longer silent. Expressions get `date`, `datetime`, `timedelta`, `days_between`. `"ok_only": true` on call rules.
- **HTTP adapter.** The start command runs in its own process group and the whole group is stopped; shutdown no longer blocks on pipes held by children; readiness requires a status below 500 (or `ready_status`); `"port"`, `"port_range"`, documented `"tools_port"`; a port already in use is a clear error; `"attribution_headers"` maps the product's own identity headers.
- Cases may be about users the backend does not know (`"unknown_user": true`, or `"unknown_users"` in poptest.json). One step's own expectation: `{"say": ..., "expect": {...}}`.
- Population: records without owners can be picked (`"owner": "any"`, automatic when the entity has no `owner_field`); `pick.where` can use `user` and `me`; errors name the goal and the reason; `"greetings": false`.
- **Mutation testing for http and cli targets** whose source is Python: `mutate --file service.py` copies the folder, swaps in the faulty file and launches it through the same start command (`"mutate": {"root": DIR}` to choose the folder). A python entry that is a wrapper around a file in another folder also works. Targets without Python source cannot be mutated; the error says so.

### Smaller fixes

- Compare: in every row `a_hits` is A and `b_hits` is B (the "fixed" rows were the wrong way round); the table headings say so.
- `private_masks` for partial or masked private values (`****1111`); `shared_with` works on entities without owners (per-user visibility).
- `id_format` ids continue after the highest fixture id.
- A step that tries to hand a session to another user is reported by `validate`.
- `say --full` / `show --full` print tool results untruncated; a progress line during long runs.
- The build-world skill no longer lists a `literal` generator.

### Behaviour changes to check when upgrading

- `world.day` / `world.date()` change at midnight rather than 24 hours after the start (cases that advance by hours across 09:00 or midnight).
- A non-`ToolError` exception in a fake tool answers 500 over HTTP instead of 400.
- `replay.shrinkable()` is kept but always true; use `replay.shrink_mode()`.
- Report layout: one section per root cause; the "same failures, as seen by the test cases' own expectations" section is gone.

## 1.0.0

First release.
