def get_ticket(world, ticket_id):
    return world.get("tickets", ticket_id)


def close_ticket(world, ticket_id):
    t = world.get("tickets", ticket_id)
    if t is None:
        return {"ok": False, "error": "no such ticket"}
    t["status"] = "closed"
    world.add("audit", id=f"a{len(world.data['audit']) + 1}", what=f"closed {ticket_id}", day=world.day)
    return {"ok": True}


def set_title(world, ticket_id, title):
    world.update("tickets", ticket_id, title=title)
    return {"ok": True}


def whoami(world, user_id):
    return world.get("users", user_id)["name"]


def boom(world):
    raise RuntimeError("backend exploded")


def set_status(world, ticket_id, status):
    world.update("tickets", ticket_id, status=status)
    return {"ok": True}


def lookup(world, entity, rid):
    return world.get(entity, rid)
