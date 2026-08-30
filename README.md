# Remote PC Agent — Vercel + Windows

This project gives an AI-facing Vercel service a secure way to queue tool requests for a Windows PC agent.

Architecture:

AI/tool client -> Vercel API -> authenticated polling -> agent.py -> Windows tools

The Windows agent makes OUTBOUND HTTPS requests to Vercel, so you do not need port forwarding.

## Included tools

- `ping`
- `list_dir`
- `read_file`
- `write_file`
- `exec` (PowerShell)
- `git_status`

## Important security model

The agent is intentionally restricted to a configured workspace directory.
`exec` is disabled by default. Enable it only after you understand the risk.

The Vercel API uses `AGENT_TOKEN`. Never put this token in browser/client-side JavaScript.

## 1. Windows agent

Install Python 3.11+.

```powershell
cd agent
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`:

```env
SERVER_URL=https://YOUR-VERCEL-DOMAIN.vercel.app
AGENT_TOKEN=use-a-long-random-secret
WORKSPACE=C:\Users\YOURNAME\Desktop\MyProject
POLL_SECONDS=1
ALLOW_EXEC=false
```

Run:

```powershell
python agent.py
```

## 2. Vercel

This starter uses Vercel Python functions and a tiny in-memory queue for development.

Set these Vercel environment variables:

```text
AGENT_TOKEN=the-same-long-random-secret
```

Deploy the `vercel` folder as the project root, or copy its contents into your Vercel project.

### Important production note

Vercel serverless functions are not a persistent database. The included queue is only a prototype.

For production, replace `api/_queue.py` with Redis/KV/Postgres/etc. Otherwise queued commands can disappear when functions restart.

## API

Queue a command:

```http
POST /api/command
Authorization: Bearer AGENT_TOKEN
Content-Type: application/json

{
  "tool": "list_dir",
  "args": {"path": "."}
}
```

The Windows agent polls:

```http
GET /api/poll
Authorization: Bearer AGENT_TOKEN
```

and submits results:

```http
POST /api/result
Authorization: Bearer AGENT_TOKEN
```

## Next step: MCP

Once this basic relay works, add a remote MCP server in front of `/api/command` so an AI client can discover:

- `read_file`
- `write_file`
- `list_dir`
- `exec`
- `git_status`

Do NOT expose arbitrary shell execution publicly without authentication and approval controls.
