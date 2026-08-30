import json
import os
import time
import uuid

import requests

QUEUE_KEY = os.getenv("REDIS_QUEUE_KEY", "remote_pc_agent:commands")
RESULT_PREFIX = os.getenv("REDIS_RESULT_PREFIX", "remote_pc_agent:result:")


def _config():
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        raise RuntimeError("Missing UPSTASH_REDIS_REST_URL or UPSTASH_REDIS_REST_TOKEN")
    return url, token


def _request(command):
    url, token = _config()
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=command,
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("result")


def enqueue(tool, args):
    command = {"id": str(uuid.uuid4()), "tool": tool, "args": args or {}}
    _request(["LPUSH", QUEUE_KEY, json.dumps(command)])
    return command


def dequeue():
    raw = _request(["RPOP", QUEUE_KEY])
    return json.loads(raw) if raw else None


def save_result(data):
    key = RESULT_PREFIX + data["id"]
    _request(["SET", key, json.dumps(data), "EX", "300"])
    return True


def get_result(command_id):
    raw = _request(["GET", RESULT_PREFIX + command_id])
    return json.loads(raw) if raw else None


def wait_for_result(command_id, timeout_seconds=8.0, interval=0.25):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = get_result(command_id)
        if result is not None:
            return result
        time.sleep(interval)
    return None
