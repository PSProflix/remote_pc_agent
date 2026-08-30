import json
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse, quote

from api._auth import authorized
from api._queue import enqueue, get_result

KIMI_TOKEN = os.getenv("KIMI_BRIDGE_TOKEN", "").strip()


def json_response(handler, data, status=200):
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def valid_token(token):
    return bool(KIMI_TOKEN) and token == KIMI_TOKEN


def execute(tool, args, timeout):
    command = enqueue(tool, args)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = get_result(command["id"])
        if result is not None:
            return command["id"], result
        time.sleep(0.5)
    return command["id"], {"ok": False, "error": f"Timed out waiting for Windows agent after {timeout} seconds", "id": command["id"]}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/kimi/exec":
            json_response(self, {"error": "not found"}, 404)
            return

        params = parse_qs(parsed.query)
        token = params.get("token", [""])[0]
        if not valid_token(token):
            json_response(self, {"error": "unauthorized"}, 401)
            return

        tool = params.get("tool", [""])[0]
        command = params.get("command", [""])[0]
        shell = params.get("shell", ["powershell"])[0].lower()
        try:
            timeout = max(1, min(int(params.get("timeout", ["60"])[0]), 300))
        except ValueError:
            timeout = 60

        if tool != "exec" or not command:
            json_response(self, {"error": "tool=exec and command are required"}, 400)
            return
        if shell not in {"cmd", "powershell"}:
            json_response(self, {"error": "shell must be cmd or powershell"}, 400)
            return

        command_id, result = execute("exec", {"command": command, "shell": shell, "timeout": timeout}, timeout + 5)
        json_response(self, {"id": command_id, "tool": "exec", "shell": shell, "command": command, "result": result})

    def do_POST(self):
        json_response(self, {"error": "This compatibility bridge intentionally accepts GET only. Use /api/command for authenticated POST clients."}, 405)

    def log_message(self, fmt, *args):
        pass
