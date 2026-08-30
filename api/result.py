from ._auth import authorized
from ._queue import save_result


def handler(request):
    if request.method != "POST":
        return {"error": "method not allowed"}, 405

    if not authorized(request):
        return {"error": "unauthorized"}, 401

    data = request.get_json(silent=True) or {}
    if not data.get("id"):
        return {"error": "missing id"}, 400

    save_result(data)
    return {"ok": True}
