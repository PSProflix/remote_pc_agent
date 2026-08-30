import json
import os
from http.server import BaseHTTPRequestHandler

from api._auth import authorized
from api._queue import enqueue, wait_for_result

TOOLS = [
    {
        "name": "ping",
        "description": "Check whether the Windows agent is online.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_dir",
        "description": "List files and directories inside the configured Windows workspace.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "default": "."}}, "additionalProperties": False},
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the configured Windows workspace.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
    },
    {
        "name": "write_file",
        "description": "Write a UTF-8 text file inside the configured Windows workspace.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False},
    },
    {
        "name": "git_status",
        "description": "Run git status in the configured Windows workspace.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "exec",
        "description": "Execute a PowerShell command in the configured workspace. Only works when ALLOW_EXEC=true on the Windows agent.",
        "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 60}}, "required": ["command"], "additionalProperties": False},
    },
]


def rpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def tool_call(name, arguments):
    allowed = {t["name"] for t in TOOLS}
    if name not in allowed:
        raise ValueError(f"unknown tool: {name}")
    command = enqueue(name, arguments or {})
    result = wait_for_result(command["id"], timeout_seconds=8.0)
    if result is None:
        raise TimeoutError("Windows agent did not return a result within 8 seconds")
    if not result.get("ok"):
        return {
            "isError": True,
            "content": [{"type": "text", "text": result.get("error", "tool failed")}],
        }
    return {
        "content": [{"type": "text", "text": json.dumps(result.get("result"), ensure_ascii=False)}],
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not authorized(self):
            self._json(rpc_error(None, -32001, "unauthorized"), 401)
            return

        try:
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(rpc_error(None, -32700, "invalid JSON"), 400)
            return

        method = body.get("method")
        request_id = body.get("id")

        if method == "initialize":
            self._json(rpc_result(request_id, {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "remote-pc-agent", "version": "1.0.0"},
            }))
            return

        if method == "notifications/initialized":
            self.send_response(204)
            self.end_headers()
            return

        if method == "tools/list":
            self._json(rpc_result(request_id, {"tools": TOOLS}))
            return

        if method == "tools/call":
            params = body.get("params") or {}
            try:
                result = tool_call(params.get("name"), params.get("arguments"))
                self._json(rpc_result(request_id, result))
            except TimeoutError as exc:
                self._json(rpc_error(request_id, -32000, str(exc)), 504)
            except Exception as exc:
                self._json(rpc_error(request_id, -32602, str(exc)), 400)
            return

        self._json(rpc_error(request_id, -32601, f"method not found: {method}"), 404)

    def do_GET(self):
        if not authorized(self):
            self._json({"error": "unauthorized"}, 401)
            return
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.end_headers()

    def _json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass
