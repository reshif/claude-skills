"""Backend client used when Expenso runs as its own process: calls the API over HTTP.
The base URL comes from the environment, so tests point it at the poptest fake-tools server
(POPTEST_TOOLS_URL) and production points it at the real API."""
import json
import os
import urllib.request


class RemoteTools:
    def __init__(self, base=None):
        self.base = (base or os.environ.get("EXPENSO_API") or os.environ["POPTEST_TOOLS_URL"]).rstrip("/")
        self.user = self.session = None

    def __getattr__(self, name):
        def call(**args):
            headers = {"Content-Type": "application/json"}
            if self.user:
                headers["X-Poptest-User"] = self.user
            if self.session:
                headers["X-Poptest-Session"] = self.session
            req = urllib.request.Request(f"{self.base}/call/{name}", json.dumps(args).encode(), headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)["result"]
        return call
