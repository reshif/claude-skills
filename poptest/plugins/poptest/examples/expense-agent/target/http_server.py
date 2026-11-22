"""Expenso as an HTTP chat service:  POST /chat {"user","session","text"} -> {"replies": [...]}.
Usage: python3 http_server.py PORT [agent_module]"""
import importlib
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from remote_tools import RemoteTools

tools = RemoteTools()
agent = importlib.import_module(sys.argv[2] if len(sys.argv) > 2 else "agent").ExpenseAgent(tools)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"ok": True})

    def do_POST(self):
        m = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        tools.user, tools.session = m["user"], m["session"]
        self._send({"replies": agent.handle(m["user"], m["session"], m["text"])})


HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
