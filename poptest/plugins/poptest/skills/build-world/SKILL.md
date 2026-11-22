---
name: build-world
description: Build the poptest sandbox for a system: the fake world (world.json) and the fake tools (tools.json + tools.py) generated from the target's API docs, schema or tool definitions. Use for "write the fake backend", "build the world", "mock our API for testing", or after connect-target in a poptest setup.
---

# Build the world and the fake tools

You are writing a small, honest imitation of everything the system can read or change. CLI path and overview: the `poptest` skill. The complete worked example is `examples/expense-agent/` in this plugin (`world.json`, `tools.json`, `tools.py`).

## 1. Inventory

From the API docs, OpenAPI file, tool/function definitions or client code, list every call the system can make: name, arguments, what it returns, what it changes. From the data model, list the record types those calls touch. Keep only what the system under test uses.

## 2. world.json

```json
{
 "clock": {"start_day": 1000, "start_date": "2026-03-02", "start_hour": 9},
 "user_entity": "users",
 "entities": {
  "users":  {"private_fields": ["bank_account", "phone"],
             "records":  [ {"id": "E01", "name": "Ana", "bank_account": "ACCT-ana-2290", "phone": "555-0111"} ],
             "generate": {"count": 40, "fields": {"id": {"seq": "U{n:03d}"}, "bank_account": {"canary": "ACCT-"},
                          "phone": {"pattern": "555-2###", "unique": true}}}},
  "orders": {"owner_field": "owner", "id_format": "EX-{n:04d}",
             "private_fields": ["note"], "detail_fields": ["merchant", "amount", "status"],
             "shared_with": "world.get('users', rec['owner'])['manager'] == user",
             "records":  [ ... ],
             "generate": {"per": "users", "where": "rec['id'].startswith('U')", "count": [2, 4], "fields": { ... }}}
 }
}
```

Rules that decide how much the checks can see:

- **`user_entity`**: the entity whose ids are the logged-in users. **`owner_field`**: on every other entity that belongs to one user. Ownership drives the cross-user checks.
- **`private_fields`**: values that must never be shown to anyone but the owner (and those `shared_with` allows). Make each value distinctive: use `{"canary": "PREFIX-"}` or a unique pattern, never a common word or a short number. A private field with a value like "yes" cannot be checked.
- **`detail_fields`**: ordinary fields (item, amount, status) that become a leak when shown **together with the id** of someone else's record. List every field the system might read out. In the blind trial, having no check of this kind was one of the gaps that let planted bugs through.
- **`shared_with`**: an expression over `rec`, `user`, `world`, `day` saying who else may see a record (a manager, an admin). Leave it out if only the owner may. It also works on an entity that has **no owner at all**: give a shared entity (stock, catalogue) `detail_fields` and `"shared_with": "not rec['restricted'] or world.get('users', user)['role'] == 'manager'"` and showing a restricted record's details to anyone else is reported as `record_detail_leak`. An entity with no `owner_field`, no `private_fields` and no `shared_with` is a public catalogue: everyone may see it.
- **`private_masks`**: partial or masked forms of a private value that are just as much a leak: `"private_masks": {"account_number": ["'****' + v[-4:]", "v[-4:]"]}` (expressions over `v`, the value, and `rec`). Without it only the whole value is looked for. Forms shorter than 4 characters are ignored (they match by accident).
- **Hand-written `records`** are the fixtures cases will lean on. Write a few users with records on every side of every limit in the spec: just inside, exactly on, just outside (29, 30, 31 days; 499.99, 500.00, 500.01), and one record in each status. Give them easy ids. Use `{"days_ago": 30}` for dates so they follow the clock (`"as": "date"` gives an ISO date instead of a day number).
- **`generate`** fills in bulk so that other users exist to leak from and collide with. Generators: a plain value (`"role": "member"`, or `{"value": ...}` for an object), `seq`, `choice`, `cycle`, `weighted`, `int`, `float` (+`round`), `pattern` (`#` digit, `?` letter), `canary`, `ref` (+`where`), `days_ago`, `template`, `if`/`then`/`else`, plus `"unique": true`. `per` makes records for each record of another entity and sets the owner.
- `"id_format": "R-{n:04d}"` is used for records made by `world.add` and by `generate`; new ids continue after the highest fixture id of that format (fixtures R-1001..R-1007 are followed by R-1008).
- Dates are day numbers by default (`world.day`); `world.date()` gives the ISO date. Keep one convention across records and tools. See "The clock" below.

### The clock

There is one injected clock. Everything below is derived from it, so the values always agree with each other:

| In `tools.py` / rules | Gives | At the start (defaults) |
|---|---|---|
| `world.day` | day number | `start_day` (1000) |
| `world.date()` | ISO date `YYYY-MM-DD`; `world.date(n)` for day number `n` | `start_date` |
| `world.now()` | ISO date and time `YYYY-MM-DDTHH:MM` | `start_date` at `start_hour` |
| `world.hour()`, `world.minute()`, `world.time()` | hour 0-23, minute, `"HH:MM"` | 9, 0, `"09:00"` |
| `world.weekday()` | 0 = Monday ... 6 = Sunday | |
| `world.days_since(x)` | whole days from a day number or ISO date to today | |

- The run starts at **09:00** unless `"clock"` says otherwise: `"start_hour": 22` or `"start_time": "22:30"`.
- The day number and the date **roll over at midnight** of that clock, together. Starting at 09:00, `{"advance": {"hours": 15}}` lands on 00:00 of the next day: `world.day` is one higher and `world.now()[:10] == world.date()`. (In 1.0 the day number rolled 24 hours after the start, i.e. at 09:00.)
- Cases move the clock with `{"advance": {"days": 1, "hours": 3, "minutes": 30}}` and can start at a time of day with `"clock": {"hour": 22}` (see `generate-cases`). `poptest say --hour 22 "..." +13h "..."` does the same by hand.
- A product with hour-level rules (opening hours, SLAs) needs a fake clock tool that returns hours: `def now(world): return {"date": world.date(), "hour": world.hour(), "iso": world.now()}`. HTTP/CLI targets can also read `GET {tools_url}/clock` (`day`, `date`, `now`, `hour`, `minute`, `time`, `weekday`).

## 3. tools.json and tools.py

```json
{"module": "tools.py",
 "tools": {
  "get_order":   {"description": "...", "args": {"order_id": {"ref": "orders"}}, "mutates": false},
  "refund":      {"description": "...", "args": {"order_id": {"ref": "orders"}}, "writes": ["orders", "refunds"]},
  "list_orders": {"args": {"user_id": {"ref": "users", "self": true}}, "mutates": false}
 }}
```

```python
def refund(world, order_id):
    o = world.get("orders", order_id)
    if o is None:
        return {"ok": False, "error": "no such order"}
    o["status"] = "refunded"
    world.add("refunds", order_id=order_id, amount=o["amount"], day=world.day)
    return {"ok": True, "amount": o["amount"]}
```

- One function per tool, named like the tool, first parameter `world`. Helpers: `world.get`, `world.where(entity, field=value)`, `world.add`, `world.update`, `world.delete`, `world.day`, `world.date()`, `world.days_since(value)`.
- Return what the real API returns, in its shape, including its error shape (next section).
- **Do not enforce product policy in the fake unless the real backend does.** If the real refund API refuses late refunds itself, refuse here too. If it trusts the caller, be permissive, because that policy is then the system's job and exactly what is under test. Ask the person when the docs do not say.
- `"ref": "<entity>"` on an argument makes the log store that record as it was before the call (`pre`), which rules rely on. `"self": true` means the argument must be the acting user's own id; anything else is reported.
- `"mutates": false` for read-only tools (faster, and they are left out of report transcripts). `"writes": [...]` narrows which entities are compared before and after.
- Always give the system a clock tool (`def today(world): return world.day`, or one returning the hour as above) if it has any time rule.
- Do not return private fields from tools that the real API does not return.

### Errors, status codes and "ok"

How the real API reports a failure decides how the fake must:

| The real API | Write in `tools.py` | An in-process target sees | An HTTP/CLI target sees |
|---|---|---|---|
| answers 200 with an error inside the body | `return {"ok": False, "error": "no such order"}` | that dict | `200 {"result": {"ok": false, ...}}` |
| answers with an error status (4xx) or raises | `raise ToolError("unknown user", status=404)` | `ToolError` raised by `tools.x(...)`: `str(e)` is the message, `e.status` the code | `404 {"error": "unknown user"}` |
| is down / times out | a case step `{"fail": {"tool": "x", "error": "timeout", "status": 503}}` (no code needed) | `ToolError`, status 503 | `503 {"error": "timeout"}` |

```python
from poptest.tools import ToolError          # available to every tools.py

def get_user(world, user_id):
    u = world.get("users", user_id)
    if u is None:
        raise ToolError("unknown user", status=404)   # default status is 400
    return {"id": u["id"], "name": u["name"]}
```

- An unknown tool is a 404; a missing or unexpected argument is a 400; **any other exception in a handler is a 500** and its text is `"ValueError: ..."`: that is a bug in the fake, so raise `ToolError` for every error the real API can give.
- **What counts as a failed call.** A raised error, and by default also a result of `{"ok": false}` or `{"error": ...}`. Failed calls do not satisfy `expect.calls`, have `ok == False` in rules, and do not need a confirmation. For a tool whose `{"ok": false}` is an ordinary answer (`verify_identity -> {"ok": false}`, `check_stock -> {"ok": false}`) declare `"ok_from_result": false` in `tools.json`; then only a raised error makes the call failed.

## 4. Check it

```
poptest validate
poptest world                      # sizes, sample records
poptest world --user E01           # one fixture user and everything they own
poptest world --entity orders --where "rec['status']=='draft' and day - rec['incurred_day'] > 60"
poptest say --user E01 "<a request>"   # the tool calls and results appear under each message
```

Compare a few fake results with real responses from the docs, field by field. A fake that returns a different shape tests a different product.

## Hand back

List for the person: the entities and how many records, which fields are private and which are details, each tool with one line on what it changes, and every place where you chose permissive or strict behaviour because the docs were silent.
