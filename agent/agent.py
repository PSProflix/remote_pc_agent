import os
import time
import subprocess
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SERVER_URL = os.environ["SERVER_URL"].rstrip("/")
TOKEN = os.environ["AGENT_TOKEN"]
WORKSPACE = Path(os.environ["WORKSPACE"]).expanduser().resolve()
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1"))
ALLOW_EXEC = os.getenv("ALLOW_EXEC", "false").lower() == "true"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def safe_path(relative_path: str) -> Path:
    """Resolve a path and prevent escaping WORKSPACE."""
    p = (WORKSPACE / relative_path).resolve()
    try:
        p.relative_to(WORKSPACE)
    except ValueError:
        raise PermissionError("Path is outside WORKSPACE")
    return p


def run_tool(tool: str, args: dict):
    if tool == "ping":
        return {"ok": True, "message": "agent is online"}

    if tool == "list_dir":
        p = safe_path(args.get("path", "."))
        if not p.is_dir():
            raise NotADirectoryError(str(p))
        items = []
        for x in p.iterdir():
            items.append({
                "name": x.name,
                "type": "directory" if x.is_dir() else "file"
            })
        return {"path": str(p), "items": items}

    if tool == "read_file":
        p = safe_path(args["path"])
        data = p.read_text(encoding="utf-8")
        return {"path": str(p), "content": data}

    if tool == "write_file":
        p = safe_path(args["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return {"path": str(p), "bytes": len(args["content"].encode("utf-8"))}

    if tool == "git_status":
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if tool == "exec":
        if not ALLOW_EXEC:
            raise PermissionError(
                "exec is disabled. Set ALLOW_EXEC=true in the agent .env."
            )

        command = args["command"]

        # PowerShell is used explicitly on Windows.
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=int(args.get("timeout", 60)),
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    raise ValueError(f"Unknown tool: {tool}")


def poll():
    r = requests.get(
        f"{SERVER_URL}/api/poll",
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def submit_result(command_id, ok, result=None, error=None):
    payload = {
        "id": command_id,
        "ok": ok,
        "result": result,
        "error": error,
    }
    r = requests.post(
        f"{SERVER_URL}/api/result",
        headers=HEADERS,
        json=payload,
        timeout=30,
    )
    r.raise_for_status()


def main():
    print(f"[agent] server: {SERVER_URL}")
    print(f"[agent] workspace: {WORKSPACE}")
    print(f"[agent] exec enabled: {ALLOW_EXEC}")
    print("[agent] waiting for commands...")

    while True:
        try:
            data = poll()
            command = data.get("command")

            if command:
                command_id = command["id"]
                tool = command["tool"]
                args = command.get("args", {})

                print(f"[agent] {tool} {args}")

                try:
                    result = run_tool(tool, args)
                    submit_result(command_id, True, result=result)
                    print(f"[agent] completed {command_id}")
                except Exception as exc:
                    submit_result(command_id, False, error=f"{type(exc).__name__}: {exc}")
                    print(f"[agent] failed {command_id}: {exc}")

        except Exception as exc:
            print(f"[agent] connection error: {exc}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
