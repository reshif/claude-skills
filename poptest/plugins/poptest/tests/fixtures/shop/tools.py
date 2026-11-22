from poptest.tools import ToolError


def get_ticket(world, ticket_id):
    t = world.get("tickets", ticket_id)
    if t is None:
        raise ToolError("no such ticket", status=404)
    return t


def update_ticket(world, ticket_id, fields):
    if world.get("tickets", ticket_id) is None:
        raise ToolError("no such ticket", status=404)
    world.update("tickets", ticket_id, **fields)
    return {"ok": True}


def pay(world, user_id, amount_minor, sku):
    rec = world.add("payments", owner=user_id, amount_minor=int(amount_minor), sku=sku)
    return {"ok": True, "id": rec["id"]}


def reserve(world, sku, qty):
    s = world.get("stock", sku)
    if s is None:
        raise ToolError("unknown sku", status=404)
    s["qty"] -= int(qty)
    return {"ok": True, "left": s["qty"]}


def get_stock(world, sku):
    return world.get("stock", sku)


def now(world):
    return {"date": world.date(), "hour": world.hour(), "now": world.now(), "day": world.day}


def verify(world, code):
    return {"ok": str(code) == "1234"}


def get_user(world, user_id):
    u = world.get("users", user_id)
    if u is None:
        raise ToolError("unknown user", status=404)
    return {"id": u["id"], "name": u["name"]}
