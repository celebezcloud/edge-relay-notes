#!/usr/bin/env python3
"""Deploy the AgentRouter relay worker to Cloudflare via REST API (no wrangler).

Credentials are read from environment variables — never hardcode them here.

    export CF_EMAIL="you@example.com"
    export CF_API_KEY="cfk_..."          # Global API Key (X-Auth-Email + X-Auth-Key)
    export CF_ACCOUNT_ID="YOUR_CF_ACCOUNT_ID"
    python3 scripts/deploy.py

Optional:
    WORKER_NAME   default: my-relay   (ganti dengan nama Worker-mu)
    WORKER_PATH   default: ../worker.js relative to this script
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

EMAIL = os.environ.get("CF_EMAIL")
KEY = os.environ.get("CF_API_KEY")
ACCT = os.environ.get("CF_ACCOUNT_ID")
SCRIPT_NAME = os.environ.get("WORKER_NAME", "my-relay")
DEFAULT_WORKER = pathlib.Path(__file__).resolve().parent.parent / "worker.js"
SCRIPT_PATH = pathlib.Path(os.environ.get("WORKER_PATH", DEFAULT_WORKER))

missing = [n for n, v in (("CF_EMAIL", EMAIL), ("CF_API_KEY", KEY), ("CF_ACCOUNT_ID", ACCT)) if not v]
if missing:
    sys.exit(f"Missing env var(s): {', '.join(missing)}. See docstring at top of this file.")
if not SCRIPT_PATH.is_file():
    sys.exit(f"Worker source not found: {SCRIPT_PATH}")

# ES module format is mandatory — the worker uses `export default { fetch }`.
metadata = {"main_module": "index.js", "compatibility_date": "2024-09-25"}

boundary = uuid.uuid4().hex
head = (
    f"--{boundary}\r\n"
    'Content-Disposition: form-data; name="metadata"\r\n'
    "Content-Type: application/json\r\n\r\n"
    f"{json.dumps(metadata)}\r\n"
    f"--{boundary}\r\n"
    'Content-Disposition: form-data; name="index.js"; filename="index.js"\r\n'
    "Content-Type: application/javascript+module\r\n\r\n"
)
body = head.encode() + SCRIPT_PATH.read_bytes() + f"\r\n--{boundary}--\r\n".encode()

url = f"https://api.cloudflare.com/client/v4/accounts/{ACCT}/workers/scripts/{SCRIPT_NAME}"
req = urllib.request.Request(url, data=body, method="PUT")
req.add_header("X-Auth-Email", EMAIL)
req.add_header("X-Auth-Key", KEY)
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
req.add_header("User-Agent", "Mozilla/5.0 (deploy-script)")

try:
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read())
    print("HTTP", resp.status)
    print(json.dumps(
        {
            "success": data.get("success"),
            "result_id": (data.get("result") or {}).get("id"),
            "errors": data.get("errors"),
        },
        indent=2,
    ))
    sys.exit(0 if data.get("success") else 1)
except urllib.error.HTTPError as exc:
    print("HTTP ERROR", exc.code)
    print(exc.read().decode(errors="replace")[:800])
    sys.exit(1)
