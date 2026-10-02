"""Run the whole app on your machine, with no AWS account.

    python scripts/local_server.py            # http://localhost:8000

Storage is in memory and the model is a rule-based stand-in, so this is for
working on the interface and the request flow. Set LLM_BACKEND=bedrock (with
AWS credentials configured) to talk to the real model from your machine.
"""
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APP_MODE", "local")
sys.path.insert(0, str(ROOT / "backend"))

from app import builder, handler  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def _api(self):
        parts = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        event = {
            "rawPath": parts.path,
            "rawQueryString": parts.query,
            "headers": {k: v for k, v in self.headers.items()},
            "requestContext": {"http": {"method": self.command, "sourceIp": self.client_address[0]}},
            "body": self.rfile.read(length).decode("utf-8") if length else "",
        }
        result = handler.handler(event)
        body = result["body"].encode("utf-8")
        self.send_response(result["statusCode"])
        for name, value in result["headers"].items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        if self.path.startswith("/api/"):
            self._api()
        elif self.command == "GET":
            super().do_GET()
        else:
            self.send_error(405)

    do_GET = do_POST = do_PATCH = do_DELETE = do_OPTIONS = _route

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main():
    port = int(os.environ.get("PORT", "8000"))
    print("Seeding the demo assistant...", builder.handler({"action": "seed_demo"}))
    print(f"Greetwell running at http://localhost:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
