"""Rules that are easier to say in Python than in rules.json.

Optional functions: on_call(ctx), on_reply(ctx), on_end(ctx). Call ctx.fail(rule_id, detail)
to report a problem. ctx has: world (true state at that moment), user, day, event, calls,
replies, user_msgs, and for on_call: tool, args, result, ok, pre, changes.
"""


def on_end(ctx):
    seen = {}
    for c in ctx.calls:
        if c["tool"] == "submit_expense" and c["ok"]:
            eid = str(c["args"].get("expense_id")).upper()
            seen[eid] = seen.get(eid, 0) + 1
    for eid, n in seen.items():
        if n > 1:
            ctx.fail("submit-once", f"expense {eid} was submitted {n} times in one conversation",
                     why="A double submission can be paid twice.")
