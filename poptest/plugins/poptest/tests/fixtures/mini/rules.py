def on_reply(ctx):
    if "forbidden-word" in ctx.text:
        ctx.fail("forbidden-word", "the system used the forbidden word")


def on_end(ctx):
    if len(ctx.user_msgs) > 50:
        ctx.fail("too-long", "conversation ran over 50 messages")
