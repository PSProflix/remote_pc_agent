import json
from http.server import BaseHTTPRequestHandler

from api._auth import authorized
from api._queue import save_result


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not authorized(self):
            self._json({"error": "unauthorized"}, 401)
            return

        try:
            length = int(self.headers.get("content-length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json({"error": "invalid JSON"}, 400)
            return

        if not data.get("id"):
            self._json({"error": "missing id"}, 400)
            return

        save_result(data)
        self._json({"ok": True})

    def _json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass
