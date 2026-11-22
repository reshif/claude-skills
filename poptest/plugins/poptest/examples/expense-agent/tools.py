"""Fake backend for Expenso. Each function is one API call the assistant can make.

Permissive on purpose: like the real API, it does not enforce policy (windows, limits,
ownership). That is the assistant's job, and exactly what the tests look at.
"""


def today(world):
    return world.day


def get_user(world, user_id):
    u = world.get("users", user_id)
    if u is None:
        return None
    return {"id": u["id"], "name": u["name"], "role": u["role"], "manager": u["manager"]}


def list_expenses(world, user_id):
    return sorted(e["id"] for e in world.where("expenses", owner=user_id))


def get_expense(world, expense_id):
    e = world.get("expenses", expense_id)
    return None if e is None else {k: v for k, v in e.items() if k != "note"}


def create_expense(world, user_id, merchant, amount):
    e = world.add("expenses", owner=user_id, merchant=merchant, amount=round(float(amount), 2),
                  status="draft", incurred_day=world.day, note="")
    return {"ok": True, "id": e["id"]}


def submit_expense(world, expense_id):
    e = world.get("expenses", expense_id)
    if e is None:
        return {"ok": False, "error": "no such expense"}
    e["status"] = "submitted"
    return {"ok": True}


def delete_expense(world, expense_id):
    if world.delete("expenses", expense_id) is None:
        return {"ok": False, "error": "no such expense"}
    return {"ok": True}


def approve_expense(world, expense_id, approver_id):
    e = world.get("expenses", expense_id)
    if e is None:
        return {"ok": False, "error": "no such expense"}
    e["status"] = "approved"
    e["approved_by"] = approver_id
    return {"ok": True}
