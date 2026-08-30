import base64
import hashlib
import html
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlparse

from api._queue import _request

ISSUER = os.getenv("OAUTH_ISSUER", "https://remote-pc-agent-le6k.vercel.app")
RESOURCE = os.getenv("MCP_RESOURCE", ISSUER + "/api/mcp")
AUTH_USER_SECRET = os.getenv("OAUTH_USER_SECRET") or os.getenv("AGENT_TOKEN", "")


def _key(prefix, value):
    return f"remote_pc_agent:oauth:{prefix}:{value}"


def _set(key, value, ttl):
    _request(["SET", key, json.dumps(value), "EX", str(ttl)])


def _get(key):
    raw = _request(["GET", key])
    return json.loads(raw) if raw else None


def _delete(key):
    _request(["DEL", key])


def _json_response(handler, data, status=200, extra_headers=None):
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Pragma", "no-cache")
    if extra_headers:
        for k, v in extra_headers.items():
            handler.send_header(k, v)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _form(handler, body, status=200):
    payload = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _pkce_ok(verifier, challenge, method):
    if not verifier or not challenge or method != "S256":
        return False
    digest = hashlib.sha256(verifier.encode()).digest()
    return secrets.compare_digest(_b64(digest), challenge)


def _oauth_error(handler, error, description, status=400, redirect_uri=None, state=None):
    if redirect_uri:
        params = {"error": error, "error_description": description}
        if state:
            params["state"] = state
        location = redirect_uri + ("&" if "?" in redirect_uri else "?") + urlencode(params)
        handler.send_response(302)
        handler.send_header("Location", location)
        handler.end_headers()
        return
    _json_response(handler, {"error": error, "error_description": description}, status)


def _authorize_get(handler, q):
    client_id = q.get("client_id", [""])[0]
    redirect_uri = q.get("redirect_uri", [""])[0]
    response_type = q.get("response_type", [""])[0]
    state = q.get("state", [""])[0]
    scope = q.get("scope", ["mcp:read mcp:write offline_access"])[0]
    code_challenge = q.get("code_challenge", [""])[0]
    code_challenge_method = q.get("code_challenge_method", [""])[0]

    client = _get(_key("client", client_id))
    if not client:
        return _oauth_error(handler, "invalid_request", "unknown client_id")
    if response_type != "code":
        return _oauth_error(handler, "unsupported_response_type", "only response_type=code is supported", redirect_uri, state)
    if redirect_uri not in client.get("redirect_uris", []):
        return _oauth_error(handler, "invalid_request", "redirect_uri is not registered")
    if not code_challenge or code_challenge_method != "S256":
        return _oauth_error(handler, "invalid_request", "PKCE S256 is required", redirect_uri, state)

    safe_name = html.escape(client.get("client_name") or client_id)
    safe_scope = html.escape(scope)
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, values in q.items() if k in {
            "client_id", "redirect_uri", "response_type", "state", "scope",
            "code_challenge", "code_challenge_method"
        } for v in [values[0]]
    )
    page = f"""<!doctype html><html><head><meta charset='utf-8'><title>Authorize remote PC agent</title>
<style>body{{font-family:system-ui;max-width:620px;margin:60px auto;padding:24px}}.box{{border:1px solid #ddd;border-radius:14px;padding:24px}}input{{width:100%;padding:12px;margin:8px 0 16px;box-sizing:border-box}}button{{padding:12px 18px;border:0;border-radius:8px;cursor:pointer}}.warn{{background:#fff3cd;padding:12px;border-radius:8px}}</style></head>
<body><div class='box'><h2>Authorize remote-pc-agent</h2><p><b>{safe_name}</b> is requesting access to your Windows agent.</p>
<p>Requested scopes: <code>{safe_scope}</code></p><div class='warn'>This can allow the connected client to read/write files and execute commands in the configured workspace.</div>
<form method='post' action='/api/oauth/authorize'>{hidden}<label>Authorization secret</label><input type='password' name='user_secret' required autocomplete='current-password'><button type='submit'>Allow</button></form></div></body></html>"""
    _form(handler, page)


def _authorize_post(handler, form):
    client_id = form.get("client_id", [""])[0]
    redirect_uri = form.get("redirect_uri", [""])[0]
    state = form.get("state", [""])[0]
    client = _get(_key("client", client_id))
    if not client or redirect_uri not in client.get("redirect_uris", []):
        return _oauth_error(handler, "invalid_request", "invalid client or redirect_uri")
    if not AUTH_USER_SECRET or not secrets.compare_digest(form.get("user_secret", [""])[0], AUTH_USER_SECRET):
        return _oauth_error(handler, "access_denied", "authorization secret is incorrect", redirect_uri, state)

    code = secrets.token_urlsafe(48)
    record = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": form.get("scope", ["mcp:read mcp:write offline_access"])[0],
        "code_challenge": form.get("code_challenge", [""])[0],
        "code_challenge_method": form.get("code_challenge_method", [""])[0],
        "created_at": int(time.time()),
    }
    _set(_key("code", code), record, 300)
    params = {"code": code}
    if state:
        params["state"] = state
    location = redirect_uri + ("&" if "?" in redirect_uri else "?") + urlencode(params)
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.end_headers()


def _register(handler, body):
    try:
        data = json.loads(body or b"{}")
    except Exception:
        return _json_response(handler, {"error": "invalid_client_metadata"}, 400)

    redirect_uris = data.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _json_response(handler, {"error": "invalid_redirect_uri", "error_description": "redirect_uris is required"}, 400)
    for uri in redirect_uris:
        parsed = urlparse(uri)
        if parsed.scheme not in {"https", "http"}:
            return _json_response(handler, {"error": "invalid_redirect_uri"}, 400)
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "[::1]"}:
            return _json_response(handler, {"error": "invalid_redirect_uri"}, 400)

    client_id = secrets.token_urlsafe(24)
    record = {
        "client_id": client_id,
        "client_name": data.get("client_name", "MCP client"),
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    _set(_key("client", client_id), record, 31536000)
    return _json_response(handler, record, 201)


def _token(handler, form):
    grant_type = form.get("grant_type", [""])[0]
    client_id = form.get("client_id", [""])[0]
    client = _get(_key("client", client_id))
    if not client:
        return _json_response(handler, {"error": "invalid_client"}, 401, {"WWW-Authenticate": "Basic realm=oauth"})

    if grant_type == "authorization_code":
        code = form.get("code", [""])[0]
        record = _get(_key("code", code))
        if not record or record.get("client_id") != client_id:
            return _json_response(handler, {"error": "invalid_grant"}, 400)
        if record.get("redirect_uri") != form.get("redirect_uri", [""])[0]:
            return _json_response(handler, {"error": "invalid_grant"}, 400)
        if not _pkce_ok(form.get("code_verifier", [""])[0], record.get("code_challenge", ""), record.get("code_challenge_method", "")):
            return _json_response(handler, {"error": "invalid_grant", "error_description": "PKCE verification failed"}, 400)
        _delete(_key("code", code))
        scope = record.get("scope", "mcp:read mcp:write offline_access")
    elif grant_type == "refresh_token":
        refresh = form.get("refresh_token", [""])[0]
        record = _get(_key("refresh", refresh))
        if not record or record.get("client_id") != client_id:
            return _json_response(handler, {"error": "invalid_grant"}, 400)
        scope = record.get("scope", "mcp:read mcp:write offline_access")
        _delete(_key("refresh", refresh))
    else:
        return _json_response(handler, {"error": "unsupported_grant_type"}, 400)

    access = secrets.token_urlsafe(48)
    refresh = secrets.token_urlsafe(48)
    token_record = {"client_id": client_id, "scope": scope, "created_at": int(time.time())}
    _set(_key("access", access), token_record, 3600)
    _set(_key("refresh", refresh), token_record, 2592000)
    return _json_response(handler, {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": refresh,
        "scope": scope,
    })


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        q = parse_qs(urlparse(self.path).query)
        route = q.get("route", [""])[0]
        if path.endswith("/.well-known/oauth-protected-resource") or path.endswith("/.well-known/oauth-protected-resource/api/mcp") or route == "protected":
            return _json_response(self, {
                "resource": RESOURCE,
                "authorization_servers": [ISSUER],
                "bearer_methods_supported": ["header"],
                "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
            })
        if path.endswith("/.well-known/oauth-authorization-server") or route == "metadata":
            return _json_response(self, {
                "issuer": ISSUER,
                "authorization_endpoint": ISSUER + "/api/oauth/authorize",
                "token_endpoint": ISSUER + "/api/oauth/token",
                "registration_endpoint": ISSUER + "/api/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": ["mcp:read", "mcp:write", "offline_access"],
            })
        if path.endswith("/authorize") or route == "authorize":
            return _authorize_get(self, q)
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        path = self.path.split("?", 1)[0]
        q = parse_qs(urlparse(self.path).query)
        route = q.get("route", [""])[0]
        if path.endswith("/register") or route == "register":
            return _register(self, raw)
        if path.endswith("/token") or route == "token":
            try:
                form = parse_qs(raw.decode("utf-8"))
            except Exception:
                return _json_response(self, {"error": "invalid_request"}, 400)
            return _token(self, form)
        if path.endswith("/authorize") or route == "authorize":
            try:
                form = parse_qs(raw.decode("utf-8"))
            except Exception:
                return _oauth_error(self, "invalid_request", "invalid form")
            return _authorize_post(self, form)
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass
