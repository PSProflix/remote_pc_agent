import json
from http.server import BaseHTTPRequestHandler

from api._auth import authorized
from api._queue import enqueue, get_result


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not authorized(self):
            self._json({"error": "unauthorized"}, 401)
            return

        try:
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json({"error": "invalid JSON"}, 400)
            return

        tool = body.get("tool")
        args = body.get("args", {})
        allowed = {"ping", "list_dir", "read_file", "write_file", "exec", "git_status"}
        if tool not in allowed:
            self._json({"error": f"unknown tool: {tool}"}, 400)
            return

        self._json(enqueue(tool, args), 202)

    def do_GET(self):
        if not authorized(self):
            self._json({"error": "unauthorized"}, 401)
            return

        command_id = self.path.split("?id=", 1)[1] if "?id=" in self.path else ""
        if not command_id:
            self._json({"error": "missing id"}, 400)
            return

        result = get_result(command_id)
        self._json({"result": result})

    def _json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass
