"""Scriptable test target. Each user message is a tiny program, so tests can make the target do
exactly the (mis)behaviour a check must catch:
  say:<text>        reply with text          do:<tool> k=v ...   call a tool, reply with result
  ask:<text>        reply with text + ?      crash:              raise
  yes / no / other  if a question from `confirm:<tool> k=v` is pending, act on yes
  flaky:<p> <rest>  with probability p treat as <rest>, else reply 'nothing'
  {entity.id.field} inside say:/ask: is replaced by the real value (so the user never typed it)
Instances keep per-session pending state and count messages (memory across sessions)."""
import random
import re


class Bot:
    def __init__(self, tools):
        self.tools = tools
        self.pending = {}
        self.seen = 0
        self.rng = random.Random()

    def run(self, cmd):
        name, *pairs = cmd.split()
        args = dict(p.split("=", 1) for p in pairs)
        return self.tools.call(name, args)

    def handle(self, user, session, text):
        self.seen += 1
        if text.startswith("flaky:"):
            p, rest = text[6:].split(" ", 1)
            if self.rng.random() >= float(p):
                return ["nothing"]
            text = rest
        text = re.sub(r"\{(\w+)\.(\w+)\.(\w+)\}",
                      lambda m: str(self.tools.lookup(entity=m.group(1), rid=m.group(2))[m.group(3)]), text)
        if text.startswith("say:"):
            return [text[4:]]
        if text.startswith("ask:"):
            return [text[4:] + "?"]
        if text.startswith("do:"):
            return [f"result {self.run(text[3:])}"]
        if text.startswith("confirm:"):
            self.pending[session] = text[8:]
            name, *pairs = text[8:].split()
            return [f"Shall I {name.split('_')[0]} " + " ".join(p.split("=", 1)[1] for p in pairs) + "?"]
        if text.startswith("crash:"):
            raise ValueError("kaboom")
        if text == "count":
            return [f"seen {self.seen}"]
        if text == "silent":
            return []
        if text.lower().startswith("yes") and " do:" in text:
            self.run(text.split(" do:", 1)[1])
            return ["It has been closed."]
        if session in self.pending and text.lower().startswith("yes"):
            self.run(self.pending.pop(session))
            return ["It has been closed."]
        self.pending.pop(session, None)
        return ["ok"]
