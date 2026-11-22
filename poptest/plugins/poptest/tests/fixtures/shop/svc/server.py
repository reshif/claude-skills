"""The shop assistant as an HTTP service: POST /chat {"user","session","text"} -> {"replies": [...]}.
Usage: python3 server.py PORT [ClassName] [warmup_seconds]
It calls its backend at $BACKEND_URL and identifies the caller with its OWN headers, X-User and
X-Session (not poptest's), as a real product would. During warm-up every route answers 503."""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot  # noqa: E402

START = time.time()
WARMUP = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0


class Backend:
    def __init__(self):
        self.base = os.environ["BACKEND_URL"].rstrip("/")
        self.user = self.session = None

    def __getattr__(self, name):
        def call(**args):
            req = urllib.request.Request(f"{self.base}/call/{name}", json.dumps(args).encode(),
                                         {"Content-Type": "application/json", "X-User": self.user or "",
                                          "X-Session": self.session or ""})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.load(r)["result"]
            except urllib.error.HTTPError as e:
                err = RuntimeError(json.load(e)["error"])
                err.status = e.code
                raise err
        return call


backend = Backend()
agent = getattr(bot, sys.argv[2] if len(sys.argv) > 2 else "Shop")(backend)


def limit():
    return 18


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
        if time.time() - START < WARMUP:
            return self._send({"error": "warming up"}, 503)
        self._send({"ok": True})

    def do_POST(self):
        m = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if time.time() - START < WARMUP:
            return self._send({"error": "warming up"}, 503)
        backend.user, backend.session = m["user"], m["session"]
        self._send({"replies": [agent.handle(m["user"], m["session"], m["text"])]})


HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
