---
name: write-rules
description: Write the poptest rules file (rules.json, optional rules.py) that says what must always hold for a system: which actions need a yes, what counts as claiming an action, which stated facts must match the data, and the product's own invariants (limits, windows, permissions, allowed status changes). Use for "write the rules/checks/invariants", after build-world in a poptest setup, or when a bug slipped through and a check must be added.
---

# Write the rules

Checks decide what the tests can see. In the blind trial behind this plugin, three of five missed bugs were check gaps (no check that a stated status was right, an address comparison that was too forgiving, no check for other customers' record details), not missing cases. Write the rules before the cases. CLI path: the `poptest` skill. Worked example: `examples/expense-agent/rules.json`.

## What you get without writing anything

From `world.json` and `tools.json` alone: crashes and errors; private field values shown to the wrong user; details of someone else's record shown next to its id; a tool changing a record owned by another user; a tool called with another user's id in a `self` argument.

Everything else comes from `rules.json`:

```json
{
 "confirmation": {"question_patterns": ["reply yes to confirm", "shall i .*\\?"]},
 "actions":    { "<tool or action name>": { ... } },
 "facts":      [ ... ],
 "invariants": [ ... ],
 "python": "rules.py"
}
```

## 1. actions: every tool that changes something

```json
"refund": {
  "label": "refunding an order",
  "needs_confirmation": true,
  "question_keywords": ["refund"],
  "must_mention": ["order_id"],
  "claims": ["has been refunded", "I(?:'ve| have) refunded"],
  "cross_user": false
}
```

- `needs_confirmation`: the call must follow, **in the same session**, a confirmation question from the system, and the user's messages since that question must end in a clear yes with no "no" among them. One yes covers one call. This catches acting on "no, please don't", acting on a yes typed in another window, and doing it twice.
- **What counts as the confirmation question.** By default a reply containing `?`. If the product confirms differently ("Reply yes to confirm or no to cancel.", "Type CONFIRM to proceed"), say how: `"question_patterns": ["reply yes to confirm"]` on the action, or once for all actions under top-level `"confirmation"`. They are regular expressions, case-insensitive; with patterns set, a `?` is no longer required and a reply is the question only if one of them matches. `question_keywords` (plain words, any one must appear) narrows either form further, e.g. to tell a refund question from a cancel question. Copy the wording from `poptest say`; with the wrong pattern every confirmed action is reported as `unconfirmed_action ... never asked (looked for ...)`.
- **One tool, several kinds of action.** When the backend has one generic tool (`update_ticket` for close, reopen, escalate) and only some uses need a yes, key the entry by an action name and say which calls it is:

  ```json
  "close_ticket": {"tool": "update_ticket", "when": "args['fields'].get('status') == 'closed'",
                   "label": "closing a ticket", "needs_confirmation": true,
                   "must_mention": ["ticket_id"], "claims": ["has been closed"]}
  ```
  `"when"` is an expression over the call (`args`, `pre`, `result`, `ok`, `user`, `world`, `day`). Findings are then named after the action (`unconfirmed_action:close_ticket`), a "has been closed" claim is only satisfied by a call that matches, and reopening needs no entry at all. Several entries may name the same tool.
- `must_mention`: argument values that must appear in that question. Catches "asked about A, did B". Each entry is one of:

  | Entry | The question must contain |
  |---|---|
  | `"order_id"` | the raw value (numbers also as `1,234` / `12.50`) |
  | `{"arg": "amount_minor", "minor_units": 2}` | the amount as written: `1999` → `19.99` (`250000` → `2,500.00` or `2500`) |
  | `{"arg": "to_account", "format": "world.get('accounts', v)['name']"}` | the text the expression gives (or any one of a list); names: `v`, `args`, `pre`, `world`, `user`, `day` |
  | `{"amount_minor": "'INR %.2f' % (v / 100)"}` | short form of `arg` + `format` |
  | `{"arg": "fields.status"}` | a value inside an object argument |

  A value only counts when it stands on its own: the `100` in `SKU-100`, `ORD-100-A`, `1,100` or `100.50` is not a quantity of 100, and other arguments' values are blanked out of the question before looking. Apart from that the comparison is exact (case and spacing aside): do not loosen it.
- `claims`: regular expressions for the system saying it did it. A match with no successful call is a false claim. First run `poptest say` and copy the real wording; make patterns specific to completion ("has been refunded"), not to the topic ("refund"). `"claim_scope": "turn"` requires the call in the same turn (good for "Added ...", "Created ...").
- `cross_user`: `true`, or an expression over `user`, `owner`, `rec`, `args`, `world` that says when changing another user's record is allowed (`"world.get('users', owner)['manager'] == user"`).
- `label`: plain words for the report.

`poptest validate` lists changing tools that have no entry here. Decide each one on purpose.

How yes and no are read is shared with the simulated users and lives in `vocab.json`. Add the product's own words there (`"affirm": ["book it"]`, `"negate": ["scrap that"]`). The reading is strict by design: "yes... actually wait" is not a clear yes, and any message since the question that contains a no-word ("don't", "cancel", "wait", "actually", ...) spoils a later yes; the finding quotes the message that was read as a no. If the spec defines a closed list of cancelling words and everything else must leave the question pending, replace the list: `{"replace": true, "negate": ["no", "cancel", "stop"]}`. If the spec is silent, a finding of this kind is an "unclear spec" question for the person, not a bug.

## 2. facts: what the system says must match the data

For every number, date, status or name the system reads out, add a fact. Two forms:

```json
{"id": "order-status", "entity": "orders", "field": "status",
 "phrases": {"shipped": ["has shipped", "on its way"], "delivered": ["was delivered"], "refunded": ["was refunded"]}}
```
When a reply names exactly one record of the entity and uses the phrases of some status, that status must be the true one.

```json
{"id": "order-amount", "entity": "orders",
 "pattern": "(?P<id>[A-Z]\\d{4})[^.]*?\\$(?P<value>[\\d,]+\\.\\d\\d)", "truth": "rec['amount']", "tolerance": 0.005}
{"id": "pending-total", "pattern": "total of \\$(?P<value>[\\d,.]+)",
 "truth": "sum(r['amount'] for r in world.where('orders', owner=user, status='pending'))"}
```
`pattern` is matched against each reply; group `value` is what was said; optional group `id` selects the record (`rec`). `truth` is an expression over `rec`, `user`, `day`, `world`. Numbers compare within `tolerance`; text compares exactly apart from case and spacing. Write patterns against real replies from `poptest say`, and check that a deliberately wrong sentence would match.

## 3. invariants: the product's own rules

Take every sentence in the spec with "only", "never", "must", "at most", "within", "before" and turn it into one of these:

```json
{"id": "refund-window", "on": "call", "tool": "refund", "when": "ok and pre['order_id'] is not None",
 "require": "day - pre['order_id']['delivered_day'] <= 30",
 "message": "An order delivered more than 30 days ago was refunded", "why": "Refund policy; late refunds cost money."}

{"id": "status-steps", "on": "change", "entity": "orders", "field": "status",
 "require": "(old, new) in [('shipped','delivered'), ('delivered','refunded')]",
 "message": "An order changed status in a way the process does not allow"}

{"id": "no-card-numbers", "on": "reply", "match": "\\b\\d{16}\\b", "require": "False",
 "message": "A full card number was shown"}

{"id": "balance-never-negative", "on": "end", "require": "all(a['balance'] >= 0 for a in world.where('accounts'))",
 "message": "An account ended below zero"}
```

| `on` | Runs | Names available |
|---|---|---|
| `call` | at each tool call (optionally one `tool` or a list), against the state **before** the call | `args, result, ok, error, pre, changes, user, day, world, calls, said` |
| `change` | for each record change a call makes (filter with `entity`, `field`, `op` = set/add/delete) | the above plus `rec` (before), `owner, old, new, id, field, op` |
| `reply` | for each reply (optionally only those matching `match`) | `text, low, m, user, day, world, calls, said, session` |
| `end` | when a conversation ends | `world, user, day, calls, changes, replies, said` |

`when` skips the rule when false; `require` must be true. `pre['<arg>']` is the record an argument pointed to, as it was before the call (needs `"ref"` on that argument in `tools.json`). `user` is the user being served. `message` (or `title`) is the report headline, in plain words a product owner would use; `why` says what it costs when broken. Prefer `on: change` state-transition rules: one of them covers every tool that could make the bad move.

- **`on: call` rules also run on calls the backend refused.** A limit rule would fire when the backend correctly rejects an over-limit transfer. Add `"ok_only": true` (or `ok and ...` in `when`) unless the rule is about the attempt itself.
- **Expressions** see the names in the table plus `re`, `date`, `datetime`, `timedelta`, `days_between(a, b)` (whole days between two ISO dates) and the usual builtins (`len`, `sum`, `any`, `all`, `min`, `max`, `sorted`, `round`, `abs`, `int`, `float`, `str`...). There is no `import`. Example: `"date.fromisoformat(args['date']) <= date.fromisoformat(world.date()) + timedelta(days=14)"`.
- `on: reply` rules also get `session_replies` and `session_user_msgs` (this window only; `calls` and `said` cover the whole conversation).
- A rule whose expression raises is not a finding: it is listed once under "Rules that could not be evaluated". Fix it.

### rules.py

Use `rules.py` (named by `"python": "rules.py"`) when an expression gets unreadable. Define any of three functions; each receives one `ctx` object and reports with `ctx.fail`:

```python
RULES = {   # optional: the headline and reason for each rule id used below
    "close-confirmed": {"title": "A ticket was closed without the user's yes", "why": "Closing is final."},
    "stock-figure": "A stock figure was stated that is not the true one",
}

def on_call(ctx):                      # every tool call, BEFORE its changes are applied to ctx.world
    if ctx.tool == "reserve" and ctx.ok and ctx.args["qty"] > ctx.pre["sku"]["qty"]:
        ctx.fail("over-reserve", f"reserved {ctx.args['qty']} of {ctx.pre['sku']['qty']}",
                 title="More was reserved than is in stock")

def on_reply(ctx):                     # every reply of the system
    if "****" in ctx.text and ctx.stance(ctx.session_user_msgs[-1]) == "no": ...

def on_end(ctx):                       # once, when the conversation ends
    ...
```

| Field | In | What it is |
|---|---|---|
| `ctx.world` | all | the true sandbox state at this moment (`world.get`, `world.where`, `world.day`, `world.now()`, `world.hour()`) |
| `ctx.user` / `ctx.case_user` | all | the user being served by this call or reply / the user named by the case |
| `ctx.day` | all | today's day number |
| `ctx.session`, `ctx.conv_id` | all | id of this conversation window (None in `on_end`); id of the conversation |
| `ctx.calls` | all | every tool call so far, all windows: dicts with `tool, args, result, ok, error, status, session, seq, user, day` |
| `ctx.replies`, `ctx.user_msgs` | all | every reply / user message so far, **all windows** (log events: `e["text"]`, `e["session"]`) |
| `ctx.session_messages` | all | **this window only**, both sides in order: `{"role": "user" or "system", "text", "seq"}` |
| `ctx.session_replies`, `ctx.session_user_msgs` | all | this window's replies / user messages as plain strings |
| `ctx.said` | all | everything the user typed so far, lower-cased (to ignore values the user gave first) |
| `ctx.stance(text)` | all | `"yes"`, `"no"` or `"other"`, read with the project's vocabulary |
| `ctx.event` | all | the raw log event |
| `ctx.tool`, `ctx.args`, `ctx.result`, `ctx.ok`, `ctx.error`, `ctx.status` | `on_call` | the call; `ok` is False for errors and `{"ok": false}` results |
| `ctx.pre` | `on_call` | records the `ref` arguments pointed to, as they were before the call |
| `ctx.changes` | `on_call`, `on_end` | the field changes of this call / of the whole conversation |
| `ctx.text` | `on_reply` | the reply |
| `ctx.fail(rule_id, detail, why=None, title=None)` | all | report `rule:<rule_id>`. `detail` is the "what happened" line |

- **Headlines.** Each rule id is its own problem in the report. Its headline is `title=` in `ctx.fail`, else the `RULES` table, else the id in words ("Rule broken: Close confirmed"). Give every rule a title a product owner would understand.
- **Two windows.** `ctx.replies` and `ctx.calls` mix all windows of the conversation. A rule about "the last confirmation question" must use `ctx.session_messages`, or it misfires in two-window cases.
- **A hook that raises does not fail silently**: the exception is reported as a warning with the line number (`rules.py on_call raised KeyError: 'tool' (rules.py line 12)`) on the console, in `say` and in the report. `ctx.event["tool"]` is the classic one: the fields are `ctx.tool`, `ctx.args`, `ctx.ok`.

## 4. Prove each rule can fire

A rule that never fires is indistinguishable from a rule that is wrong.

1. `poptest validate` (syntax, patterns, unknown tools, entities and arguments).
2. `poptest run` on the unmodified system: expect no findings. A rule that fires here is either a real bug (show the person) or a wrong rule (fix it). A rule that "could not be evaluated" is listed as a warning in the report: fix the expression.
3. Later, `mutation-score` plants faults; any rule that never catches one deserves a second look.

## Hand back

A table for the person: each rule, the spec sentence it comes from, and anything in the spec you could not turn into a check (say why: no observable signal, or it is a matter of quality).
