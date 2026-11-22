---
name: connect-target
description: Connect poptest to the real system under test and point that system's tools at the fake-tools sandbox. Use at the start of a poptest setup, for "connect my agent/bot/API", "set up poptest", or when `poptest validate` reports the target cannot start. Covers the three adapters (in-process Python, HTTP chat endpoint, command-line process).
---

# Connect the target

Goal: `poptest say --user <id> "hello"` prints a real reply from the real system, and any tool the system calls shows up as a line under the message. CLI path: see the `poptest` skill.

## 1. Start a project

`poptest init <dir>` beside the system's code gives a small runnable **sample** (a task list) to copy from; `poptest init <dir> --bare` gives empty files and nothing to clean up; `--example expense-agent` gives a complete worked example to read. Everything below edits `<dir>/poptest.json`.

The sample's files refer to each other. When you replace `world.json` and `tools.json`, also replace `rules.json` and delete `population.json`, `cases/starter.json` and `target/`; `poptest validate` names every leftover that still points at a sample tool or entity ("population.json: goal 'delete_task' picks from entity 'tasks', which is not in world.json"). `validate` never prints a traceback: a line starting `PROBLEM:` or `poptest:` is the whole story. (`POPTEST_DEBUG=1` shows a traceback if you need one.)

## 2. Find the two seams

Read the system's code and config and locate:

1. **The way in:** how one user message is handed to it and how replies come back. A function, an HTTP route, or a process reading stdin.
2. **The way out:** where it calls its tools or backends (database client, payments API, email, MCP server, function-calling tool table). This must be redirected to the sandbox. Look for a base URL, a client object passed in, an environment variable, or a tool registry.

If the way out cannot be redirected without editing the system, stop and tell the person the two options: add a small injection point (a constructor argument or a base-URL setting, which is good practice anyway), or accept reply-only checks. Never mock by editing the system's logic.

## 3. Pick the adapter

**python** (best while developing; needed for `mutate`):

```json
"target": {"adapter": "python", "entry": "path/to/file.py:ClassName", "timeout": 20}
```

The class is constructed once per fresh instance as `ClassName(tools)` and must offer `handle(user, session, text)` returning a string, a list of strings, or `{"replies": [...]}`. `tools` is the sandbox: `tools.refund(order_id="A1")` calls the fake tool `refund`. If the real class has another shape, write a thin wrapper file in the project (10 to 30 lines) that builds the real agent with the sandbox as its tool client and forwards `handle`. A function `entry` is also accepted: `fn(user, session, text, tools)`. Put the wrapper in the poptest project, not in the product.

**http** (deployed or containerised service):

```json
"target": {"adapter": "http", "url": "http://127.0.0.1:{port}/chat",
           "request": {"user": "{user}", "session": "{session}", "text": "{text}"},
           "reply_path": "replies",
           "start": {"command": ["python3", "server.py", "{port}"], "ready_url": "http://127.0.0.1:{port}/health"},
           "reset": "restart"}
```

poptest starts its fake-tools server and gives the address to the target in the environment variable `POPTEST_TOOLS_URL` (also `{tools_url}` inside `command`, `env`, `url`). Configure the target so its backend base URL is that address. A target that reads its own variable gets it through `env` (http and cli alike): `"env": {"BACKEND_URL": "{tools_url}", "APP_MODE": "test"}`. Placeholders: `{tools_url}`, `{tools_port}`, `{port}`, `{root}` (the project folder). The server speaks: `POST /call/<tool>` with a JSON object of arguments, returning `{"result": ...}` or an error status with `{"error": ...}`; `GET /tools`; `GET /clock`. If the real backend has a different wire format, add a small client shim on the target side or a translating wrapper. `request` is the JSON body template; `reply_path` is the dotted path to the reply text or list. `reset` is `"restart"` (a new process for every fresh instance), `{"url": ...}` (an endpoint that clears state), or omitted for an already running service (then state leaks between cases: say so in the report). `"cwd"` sets the folder the command runs in (relative to the project).

**Errors from the fake backend.** A fake tool that raises `ToolError("unknown user", status=404)` answers `404 {"error": "unknown user"}`; see `build-world`, "Errors, status codes and ok".

**Who made the call (attribution).** Every tool call is attributed to a user and a session. By default that is the message being handled, which is right for a target that handles one message at a time. A service that handles several users at once should say who it is calling for. If it already sends its own identity headers to its backend, map them, no code change needed:

```json
"attribution_headers": {"user": "X-User", "session": "X-Session"}
```
(each value may be a list). `X-Poptest-User` / `X-Poptest-Session` are always accepted and win. The user header must carry the user id as it is in `world.json`, the session header the session id poptest sent with the message.

**Ports.** `{port}` is a free port chosen by poptest. On a shared machine fix it or confine it:

- `"port": 8123` fixes the target's port and `"tools_port": 8124` the fake-tools server's.
- `"port_range": [8100, 8199]` takes the first free ports in that range for both.
With a fixed port poptest waits for the previous process to release it and otherwise stops with "port 8123 is already in use" rather than talking to whatever is listening there.

**Start, stop, ready.** The start command runs in its own process group, and stopping the target stops the whole group, so a launcher script, `sh -c`, `npm run` or a process manager that starts the real server as a child is fine: nothing is left behind holding the port. The target is ready when `ready_url` (default: the chat URL) answers with a status below 500; a 502/503 from a proxy or a warming-up server is "not yet". `"ready_status": 200` (or a list) demands exact codes; `"ready_timeout": 15` is the limit in seconds, and the error says what the last answer was. A process that exits at start is reported with its last lines of stderr.

**cli** (a program that chats on stdin/stdout):

```json
"target": {"adapter": "cli", "command": ["python3", "bot.py"], "protocol": "jsonl"}
```

`jsonl`: one line in `{"user","session","text"}`, one line out (`{"replies": [...]}` or plain text), one process for everything. `text`: the message as a line, one reply line back (or lines up to `end_marker`), one process per session; `{user}` and `{session}` may appear in `command`, and `POPTEST_USER` / `POPTEST_SESSION` are set.

## 4. Replies that are random by specification (noise)

Some systems are specified to answer a small share of messages with a non-answer ("Sorry, could you repeat that?") that has no side effects and that clients are expected to send again. Do **not** wrap the target or switch the branch off: declare it in `poptest.json`.

```json
"noise": {"replies": ["^Sorry, could you repeat that\\?$"], "max_resends": 3}
```

- `replies` are regular expressions (case-insensitive). A turn is noise when every reply of that turn matches one.
- The noise reply is recorded in the log and shown in transcripts, the same message is sent again (up to `max_resends` times, default 3), and only the real answer takes part in checks, expectations and what a simulated user sees. A resend is not a new user message.
- **The promise "no side effects" is checked**: if the noise turn changed data, that is the finding `noise_side_effect:<tool>`.
- If the reply still matches after `max_resends`, it is not noise but the system's answer to that message, and it is checked like any reply.
- The report states how often it happened ("19 of 653 sent messages (2.9%)"), so the spec's rate can be compared.
- A target config may carry its own `"noise"` (for example in the A or B file of a comparison); it replaces the project's.

Make the patterns exact (anchor them with `^...$`): a pattern that also matches real answers hides them.

## 5. The clock

Anything date-dependent must read the sandbox clock, or time-jump cases test nothing. Give the system a `today`-style fake tool (see `build-world`, "The clock": `world.now()`, `world.hour()`, start hour, midnight roll-over) or have it read `GET /clock`. If it uses the machine's clock and that cannot change, tell the person: clock cases will be skipped and only session order is tested.

## 6. Identity

poptest passes a user id with every message, as a logged-in user. Map it to however the system identifies its caller (a header, a token lookup, a constructor field). The ids are the ids of the user entity in `world.json`. A user the backend does not know is tested with a case marked `"unknown_user": true` (see `generate-cases`); `poptest say --user nobody "hello"` works without any marking.

## 7. Prove it

```
poptest validate
poptest say --user <a real id from `poptest world`> "hello" "<a request that needs a tool>"
```

You must see a reply and at least one `(the system did: ...)` line. No action lines means the tools are not redirected: fix that before anything else, because every action check depends on it.

## Hand back

Tell the person: which adapter, where the wrapper or config lives, whether a fresh instance per case is real (or state can leak), whether the clock is injected, and whether noise replies are declared.

## Not possible

- Real concurrency: messages are sent one at a time, so a missing lock is invisible.
- Two different users on the **same** session id: every session in a case has its own id.
