---
name: generate-cases
description: Write 150-250 targeted, scripted, multi-session poptest cases from a system's spec, covering a checklist of failure families (boundaries, mind changes including negated phrasing, wrong ids, split messages, topic switches, cross-user, cross-session, concurrent sessions, clock, permissions, record-detail leaks). Also configures the secondary population mode (simulated users). Use for "write test cases", "generate cases", "more coverage", or after write-rules in a poptest setup.
---

# Generate cases

Targeted cases written from the spec are the strongest tool here: in the blind trial they found 12 of 20 planted bugs against 8 for a simulated population. Your job is to think like the person who will break this system, and to write it down as scripts. CLI path: the `poptest` skill. Worked example: `examples/expense-agent/cases/` (89 cases).

## Before writing

1. Read the spec end to end. List every **action**, every **limit** (numbers, dates, counts), every **permission**, every **privacy statement**.
2. `poptest world` and `poptest world --user <fixture>`: you need real ids. If a situation needs a record that does not exist, add a fixture record to `world.json` or use `setup` in the case. Never guess ids.
3. `poptest say --user <id> "..."` for each action once, to learn the system's real wording and what a confirmation looks like.

## Case format

One or more JSON files in `cases/`, each a list:

```json
{"id": "window-closes-before-yes", "family": "clock", "title": "Asked on day 60, confirmed on day 61",
 "user": "E01",
 "setup": [{"entity": "expenses", "id": "EX-9001", "set": {"incurred_day": {"days_ago": 59}}}],
 "steps": [
   "submit EX-9002",
   {"advance": {"days": 1}},
   {"session": "b", "say": "yes"},
   {"session": "ben", "user": "E02", "say": "status of EX-9101"},
   {"patch": [{"entity": "expenses", "id": "EX-9002", "set": {"status": "rejected"}}]},
   {"close": "b"}
 ],
 "expect": {
   "calls":     [{"tool": "submit_expense", "args": {"expense_id": "EX-9001"}, "count": 1}],
   "no_calls":  [{"tool": "submit_expense", "args": {"expense_id": "EX-9002"}}, "delete_expense"],
   "world":     [{"entity": "expenses", "id": "EX-9002", "field": "status", "equals": "draft"},
                 {"entity": "expenses", "id": "EX-0000", "exists": false},
                 {"expr": "len(world.where('expenses', owner=user)) == 8"}],
   "unchanged": ["users", {"entity": "expenses", "id": "EX-9101"}],
   "reply_contains": ["..."], "reply_not_contains": ["..."], "reply_matches": ["regex"],
   "last_reply_contains": ["..."], "last_reply_not_contains": ["..."]
 }}
```

All expectation keys (`validate` rejects any other): `calls`, `no_calls`, `world`, `unchanged`; `reply_contains`, `reply_not_contains`, `reply_matches`, `reply_not_matches` (**every** reply of the conversation, all windows and users, joined); and the same four with `last_reply_` (only the replies to the final message).

- A step that is a plain string is a message in the session `main`. Name sessions to open several **at the same time**; steps run in the order written, so interleaving is explicit. A session belongs to the case's `user` unless its first step names another; a later step cannot hand it to someone else (`validate` reports that), so give every other user their own session name.
- **One step's own expectation.** `{"say": "show T-1", "expect": {"reply_contains": ["open"], "reply_not_contains": ["internal"], "no_calls": ["update_ticket"]}}` looks only at the replies and calls of that turn (keys: `calls`, `no_calls`, `reply_contains`, `reply_not_contains`, `reply_matches`, `reply_not_matches`). Use it when a whole-conversation `reply_not_contains` would trip over an earlier, legitimate reply or over another user's window.
- `advance` moves the injected clock (days, hours, minutes). The run starts at 09:00 (or the world's `start_hour`) and the day changes at midnight; `"clock": {"hour": 22}` on the case starts it at 22:00 (`"minute"`, `"days"` also allowed), so an after-hours case needs no arithmetic. See `build-world`, "The clock".
- `patch` changes the world from outside mid-conversation (a delivery arrives, an admin rejects something). `close` ends a session; saying something in it again opens a new one with a new id (`<case>:<name>#2`).
- `{"fail": {"tool": "make_transfer", "error": "timeout", "status": 503}}` makes the next call of that fake tool fail as a backend outage would, without running it (`"tool": "*"` for any tool, `"times": 3` or `"always"`, `{"fail": {"clear": true}}` to end it). Use it for every "on any backend failure ..." sentence of the spec.
- **A user the backend does not know.** `"user": "mallory", "unknown_user": true` lets a case run as someone who is not in the world (or list such ids once under `"unknown_users"` in `poptest.json`). Without the flag an unknown user is reported as a mistake in the case.
- `calls` / `no_calls` arguments match partially: only the arguments you name are compared, and inside an object argument only the keys you name (`{"tool": "update_ticket", "args": {"fields": {"status": "closed"}}}` matches a call that also sets `closed_date`). `"ok": false` in an entry counts refused calls too. A call the backend refused, or whose result is `{"ok": false}`, does not count as having happened (unless the tool is declared `"ok_from_result": false`).
- `setup` patches the world before the first message: `set`, `add`, `delete`. `{"days_ago": N}` resolves against the clock.
- `"group": "name"` makes cases share one world and one running instance, in file order. Use it only for cross-case memory; otherwise every case gets a fresh world and a fresh instance.
- The simpler form `"sessions": [{"day_offset": 0, "messages": [...]}, {"day_offset": 2, "messages": [...]}]` works for one-user, one-after-another sessions.
- **Expectations state the correct outcome in terms of actions and data**, not wording: `calls` (succeeded; `count` for exactly), `no_calls`, `world`, `unchanged`. Use reply text only for facts the reply must or must not contain. Every refusal case gets `no_calls` and `unchanged`. The generic checks (privacy, confirmation, rules) run on every case anyway; do not restate them.

## The checklist: 150-250 cases across these families

Set `family` to exactly these names; `poptest validate` counts them and lists families with none. Rough share in brackets. For each family, go through **every action** in the spec.

1. **happy_path** (5%): each action done right once. If these fail, nothing else means anything.
2. **boundary** (15%): for every limit: just inside, exactly on, just outside. Both directions. Zero, one, empty, maximum. Wrong starting state for each action (already done, not yet eligible).
3. **mind_change** (8%): no after the question; "no wait"; no then a bare yes (must not revive it); cancel then ask again and confirm (exactly once); "never mind" mid-flow.
4. **negated_phrasing** (8%): ways of saying no that contain no "no", or contain a "yes": "please don't", "I'd rather you didn't", "do not", "don't" with a curly apostrophe, "yes... actually wait", "yeah no", "not yet", "hold on". One per case, so a failure names the phrase. The trial's population missed a bug for lack of exactly "no, please don't".
5. **wrong_id** (7%): an id that does not exist; a near miss of the user's own id; someone else's valid id; lower case, missing dash, extra spaces; wrong id then the right one (the yes must apply to the right one only).
6. **split_messages** (6%): request and id in separate messages; one thought over three messages; "yes" then "please"; the id arriving after an unrelated message.
7. **topic_switch** (6%): a different request while a confirmation is pending, then "yes" (the old question must be dead); switch and come back; two pending actions of different kinds.
8. **cross_user** (8%): each read and each action aimed at another user's record; asking for another user's private fields by name and by id; a second user creating data mid-case, then the first user listing theirs.
9. **cross_session** (6%): question in one session, yes in the next; state that must persist across sessions (and state that must not); a half-given request continued in a new session.
10. **concurrent_sessions** (6%): **two sessions of the same user open at once**: question in A and yes in B; a pending action in each, confirmed in the right windows; the same request in both, declined in one and confirmed in the other (once only). Then two different users interleaved. The trial's population never created this situation and missed the bug that lives there.
11. **clock** (6%): cross a limit between the question and the yes; make a record expire by waiting; exactly-on-the-limit after a jump; ages and dates the system states after a jump.
12. **permissions** (6%): every role attempting every action it may not do; acting on one's own record where a second person is required; acting on another team's record; a record in the wrong state.
13. **record_detail_leak** (5%): every phrasing of every request, aimed at someone else's record id, expecting that none of its details appear (`reply_not_contains`). Different verbs reach different code paths.
14. **messy_input** (4%): upper case, typos in the verb, punctuation only, empty message, a long ramble with the request inside, pasted signature.
15. **repeat_action** (4%): yes twice; the whole request twice; undoing something already undone.

Where the product has more actions than the example, scale the count, not the share. Stop at about 250: past that, mutation testing (see `mutation-score`) is a better guide to what is missing than more of the same.

## How to write them efficiently

- Work family by family, one file per family (`cases/boundary.json`). For a large spec, hand each family to a `case-writer` subagent with the spec, the fixture list from `poptest world`, the tool list and this format; then merge.
- **Or write a generator script.** 150-250 cases by hand in JSON is slow; a short Python script in the project (`gen/make_cases.py`) that loops over roles, limits, hours and phrasings and writes the `cases/<family>.json` files is the efficient way and is what most projects end up with. Keep the script in the project, keep one idea per case, and still read every generated failure. Generated ids must be stable (no random suffixes) so runs can be compared.
- If the target has declared noise replies (`connect-target`), write cases as if they did not exist: the harness resends.
- Vary the wording between cases (terse, polite, messy) so that phrasing coverage comes for free.
- After each file: `poptest validate`, then `poptest run --only <family>`.
- **Every failure on first run is either a product bug or a wrong case. Read each one** (`poptest show latest <case>`). Fix wrong cases; keep and report real bugs. If the spec does not say what should happen, ask the person rather than encode a guess. Do not weaken an expectation just to make it pass.

## Population mode (secondary)

Simulated users add what scripts cannot plan: many users at once on one shared world, and wording nobody chose. Configure `population.json`:

```json
{"goals": {
   "submit_ok": {
     "pick": {"entity": "expenses", "where": "rec['status']=='draft' and day - rec['incurred_day'] <= 60"},
     "open": ["submit {id}", "please submit expense {id}"], "open_without": ["I want to submit an expense"],
     "answers": {"id": ["{id}", "it's {id}"]}, "later": ["what's the status of {id}?"],
     "expect": {"calls": [{"tool": "submit_expense", "args": {"expense_id": "{id}"}}]}},
   "peek_other": {"pick": {"entity": "expenses", "owner": "other"}, "open": ["status of {id}"],
                  "expect": {"no_calls": ["submit_expense"]}},
   "add": {"slots": {"amount": {"float": [5, 90]}, "merchant": {"choice": ["Corner Deli"]}},
           "open": ["add expense {amount} at {merchant}"]}},
 "cues": {"ask:id": ["which expense", "expense number"]}}
```

- A **goal** is something a user wants, with the true outcome attached (`expect`, same format as cases). `pick` chooses a record whose state makes that outcome correct, and with it the user:
  - `{"entity": E}`: a record the user owns (`"owner": "self"`, the default);
  - `{"entity": E, "owner": "other"}`: a record that belongs to somebody else. Staff who may legitimately see other people's records are "other" too: exclude them with `user_where`;
  - `{"entity": E, "owner": "any"}`: any record. This is also what happens when the entity has **no `owner_field`** (shared records such as stock or a catalogue): any user is paired with any record;
  - `"where"`: an expression over `rec`, `world`, `day`, `owner` (the owner's user record) and, for the user being tried, `user` (id) and `me` (their record), e.g. `"rec['warehouse'] == me['warehouse']"`;
  - `"user_where"`: an expression over `rec` (the user's record), e.g. `"rec['role'] == 'picker'"`;
  - no `pick` at all: any user, with only `slots`.
  Write one goal per action for the allowed case and one per reason it must be refused. `validate` names a goal whose entity does not exist or for which no user can be built, and says why.
- `{id}`, `{rec[field]}`, `{me[field]}` and your own `slots` fill the templates (`open`, `answers`, `expect`).
- Polite simulated users sometimes put "Hi there. " in front of a request. For a strict command-style product that the spec does not require to understand that, set `"greetings": false` (top level, or on one goal).
- **`cues`** tell the simulated user what the system is asking for: `ask:<slot>` patterns copied from real replies. Built-in cues cover confirmation questions, refusals, completions and confusion; extend them if the system words things unusually (`"confirm": ["type CONFIRM"]`). The `question_patterns` declared in `rules.json` are used as confirmation cues automatically, so simulated users answer "Reply yes to confirm or no to cancel." with a yes or a no.
- Traits (patience, style, knowledge, quirk, timing) are combined so every pair of values occurs. Quirks include changing one's mind, negated no, wrong details, topic switches, split messages; timing includes coming back days later and a second window while an action is pending.
- Extend `vocab.json` with how this product's users talk (`"say": {"negated_no": {"messy": ["nah leave it"]}}`).

`poptest personas` previews them; `poptest run --population --budget 600` runs them. Unmet goals are reported as lower-confidence signals: read the conversation before calling it a bug.
