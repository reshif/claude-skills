"""A tiny sample target so that `poptest run` works straight after `poptest init`.
REPLACE THIS with a connection to your real system (see the connect-target skill).

The only contract: a class taking `tools`, with handle(user, session, text) -> list of replies.
"""
import re

ID = re.compile(r"\bT-?(\d{4})\b", re.I)


class TaskAgent:
    def __init__(self, tools):
        self.tools = tools
        self.pending = {}  # session -> task id waiting for a yes

    def handle(self, user, session, text):
        low = text.lower().strip()
        m = ID.search(text)
        tid = f"T-{m.group(1)}" if m else None
        if session in self.pending:
            target = self.pending.pop(session)
            words = re.sub(r"[^a-z' ]", " ", low).split()
            if words[:1] and words[0] in ("yes", "yeah", "yep", "ok", "sure") and not \
                    {"no", "not", "don't", "dont", "wait", "stop"} & set(words):
                self.tools.delete_task(task_id=target)
                return [f"{target} has been deleted."]
            if not tid:
                return ["OK, I won't delete it."]
        if low.startswith("add "):
            res = self.tools.add_task(user_id=user, title=text[4:].strip())
            return [f"Added {res['id']}."]
        if "list" in low:
            ids = self.tools.list_tasks(user_id=user)
            return [f"You have {len(ids)} tasks: " + ", ".join(ids)]
        if tid and ("delete" in low or "done" in low):
            task = self.tools.get_task(task_id=tid)
            if not task or task["owner"] != user:
                return [f"I can't find task {tid}."]
            if "delete" in low:
                self.pending[session] = tid
                return [f"Shall I delete {tid} ({task['title']})?"]
            self.tools.complete_task(task_id=tid)
            return [f"I've marked {tid} as done."]
        if "delete" in low or "done" in low:
            return ["Which task? Give me its number, like T-0001."]
        return ["I can add, list, complete and delete tasks."]
