import json
from http.server import BaseHTTPRequestHandler

from api._auth import authorized
from api._queue import enqueue, wait_for_result

RESOURCE_METADATA = "https://remote-pc-agent-le6k.vercel.app/.well-known/oauth-protected-resource/api/mcp"

TOOLS = [
    {"name": "ping", "description": "Check whether the Windows agent is online.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_dir", "description": "List files and directories inside the configured Windows workspace.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "default": "."}}, "additionalProperties": False}},
    {"name": "read_file", "description": "Read a UTF-8 text file inside the configured Windows workspace.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "write_file", "description": "Write a UTF-8 text file inside the configured Windows workspace.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}},
    {"name": "git_status", "description": "Run git status in the configured Windows workspace.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {
        "name": "exec",
        "description": "Execute a Windows CMD or PowerShell command in the configured workspace and return stdout, stderr, and exit code. Commands can run for up to 300 seconds.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "shell": {"type": "string", "enum": ["powershell", "cmd"], "default": "powershell"},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 300}
            },
            "required": ["command"],
            "additionalProperties": False
        }
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
    # Commands such as npm, pip, builds and PowerShell scripts often take longer
    # than the old 8-second window. Keep the MCP HTTP request alive long enough
    # for the Windows agent to finish and return its complete output.
    result = wait_for_result(command["id"], timeout_seconds=180.0, interval=0.5)
    if result is None:
        raise TimeoutError("Windows agent did not return a result within 180 seconds")

    if not result.get("ok"):
        return {"isError": True, "content": [{"type": "text", "text": result.get("error", "tool failed")}]}

    value = result.get("result")
    # Keep the response deterministic and readable for MCP clients/LLMs.
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        auth = authorized(self)
        if not auth:
            self._unauthorized()
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
                "serverInfo": {"name": "remote-pc-agent", "version": "2.1.0"},
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
            scope = auth.get("scope", "")
            if "mcp:write" not in scope and not auth.get("legacy"):
                self._json(rpc_error(request_id, -32003, "mcp:write scope required"), 403)
                return
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
            self._unauthorized()
            return
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.end_headers()

    def _unauthorized(self):
        self._json({"error": "unauthorized"}, 401, {"WWW-Authenticate": f'Bearer resource_metadata="{RESOURCE_METADATA}"'})

    def _json(self, data, status=200, extra_headers=None):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass
