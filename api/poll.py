from ._auth import authorized
from ._queue import dequeue


def handler(request):
    if request.method != "GET":
        return {"error": "method not allowed"}, 405

    if not authorized(request):
        return {"error": "unauthorized"}, 401

    command = dequeue()
    return {"command": command}
