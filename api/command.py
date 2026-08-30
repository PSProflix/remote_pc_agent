from ._auth import authorized
from ._queue import enqueue


def handler(request):
    if request.method != "POST":
        return {"error": "method not allowed"}, 405

    if not authorized(request):
        return {"error": "unauthorized"}, 401

    body = request.get_json(silent=True) or {}
    tool = body.get("tool")
    args = body.get("args", {})

    allowed = {"ping", "list_dir", "read_file", "write_file", "exec", "git_status"}
    if tool not in allowed:
        return {"error": f"unknown tool: {tool}"}, 400

    command = enqueue(tool, args)
    return command, 202
