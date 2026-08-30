# Prototype-only in-memory queue.
# Replace this with Redis/KV/Postgres for production.
import threading
import uuid

_lock = threading.Lock()
_pending = []
_results = {}


def enqueue(tool, args):
    command = {
        "id": str(uuid.uuid4()),
        "tool": tool,
        "args": args or {},
    }
    with _lock:
        _pending.append(command)
    return command


def dequeue():
    with _lock:
        if not _pending:
            return None
        return _pending.pop(0)


def save_result(data):
    with _lock:
        _results[data["id"]] = data


def get_result(command_id):
    with _lock:
        return _results.get(command_id)
