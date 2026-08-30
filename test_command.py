import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv("agent/.env")

url = os.environ["SERVER_URL"].rstrip("/") + "/api/command"
token = os.environ["AGENT_TOKEN"]

tool = sys.argv[1] if len(sys.argv) > 1 else "ping"
args = {}

if tool == "list_dir":
    args["path"] = sys.argv[2] if len(sys.argv) > 2 else "."
elif tool == "read_file":
    args["path"] = sys.argv[2]
elif tool == "exec":
    args["command"] = " ".join(sys.argv[2:])

r = requests.post(
    url,
    headers={"Authorization": f"Bearer {token}"},
    json={"tool": tool, "args": args},
    timeout=30,
)
print(r.status_code)
print(r.text)
