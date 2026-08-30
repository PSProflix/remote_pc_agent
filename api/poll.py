import json
from http.server import BaseHTTPRequestHandler

from api._auth import authorized
from api._queue import dequeue


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authorized(self):
            self._json({"error": "unauthorized"}, 401)
            return
        self._json({"command": dequeue()})

    def _json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass
