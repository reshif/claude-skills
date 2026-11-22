RULES = {
    "no-shouting": {"title": "The assistant shouted at the user", "why": "House style: never all capitals."},
    "greeting-first": "A session did not start with a greeting",
}


def on_reply(ctx):
    if ctx.text.isupper() and len(ctx.text) > 8:
        ctx.fail("no-shouting", f"reply in capitals: {ctx.text[:40]}")
    if "session-probe" in ctx.text:
        ctx.fail("probe", " | ".join(f"{m['role']}:{m['text']}" for m in ctx.session_messages))
    if "explode-hook" in ctx.text:
        ctx.event["nope"]


def on_call(ctx):
    if ctx.tool == "reserve" and ctx.ok and ctx.args["qty"] > 50:
        ctx.fail("reserve-limit", f"reserved {ctx.args['qty']} at once", title="More than 50 units were reserved at once")
    if ctx.tool == "pay" and ctx.ok and ctx.args["amount_minor"] > 100000:
        ctx.fail("big_payment", f"paid {ctx.args['amount_minor']}")
