"""Fake tools: one function per call your system makes to the outside world.

Signature: def tool_name(world, **args). Read and change the sandbox through `world`:
  world.get(entity, id)   world.where(entity, field=value)   world.add(entity, field=...)
  world.update(entity, id, field=...)   world.delete(entity, id)   world.day   world.date()
Return plain JSON data shaped like your real API's responses. Do not enforce your product's
policy here unless the real backend does: policy is what the tests check the system for.
"""


def list_tasks(world, user_id):
    return sorted(t["id"] for t in world.where("tasks", owner=user_id))


def get_task(world, task_id):
    return world.get("tasks", task_id)


def add_task(world, user_id, title):
    t = world.add("tasks", owner=user_id, title=title, done=False, created_day=world.day)
    return {"ok": True, "id": t["id"]}


def complete_task(world, task_id):
    t = world.get("tasks", task_id)
    if t is None:
        return {"ok": False, "error": "no such task"}
    t["done"] = True
    return {"ok": True}


def delete_task(world, task_id):
    if world.delete("tasks", task_id) is None:
        return {"ok": False, "error": "no such task"}
    return {"ok": True}
