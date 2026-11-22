"""Expenso as a command-line process: one JSON message per line on stdin, one JSON reply per
line on stdout."""
import json
import sys

from agent import ExpenseAgent
from remote_tools import RemoteTools

tools = RemoteTools()
agent = ExpenseAgent(tools)
for line in sys.stdin:
    if not line.strip():
        continue
    m = json.loads(line)
    tools.user, tools.session = m["user"], m["session"]
    print(json.dumps({"replies": agent.handle(m["user"], m["session"], m["text"])}), flush=True)
