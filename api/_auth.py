import json
import os

from api._queue import _request


def _oauth_access_token_valid(token):
    if not token:
        return None
    raw = _request(["GET", "remote_pc_agent:oauth:access:" + token])
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def authorized(request, allow_legacy=True):
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None

    token = header[7:].strip()
    if allow_legacy:
        expected = os.environ.get("AGENT_TOKEN")
        if expected and token == expected:
            return {"scope": "mcp:read mcp:write offline_access", "legacy": True}

    return _oauth_access_token_valid(token)
