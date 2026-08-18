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
    RELAY_ALLOWED_KEY  AgentRouter key yang diizinkan pakai relay ini (worker v5
                       auth gate). Kosongkan untuk relay terbuka (legacy).
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
    if not data.get("success"):
        sys.exit(1)
except urllib.error.HTTPError as exc:
    print("HTTP ERROR", exc.code)
    print(exc.read().decode(errors="replace")[:800])
    sys.exit(1)

# --- Optional: single-tenant auth gate (worker v5) -------------------------
# Set RELAY_ALLOWED_KEY to the AgentRouter key that may use this relay. The
# worker then rejects every other Authorization header with 401 before ever
# contacting the upstream — a copied repo / leaked URL is useless without it.
# Skip this to keep the relay open (legacy behavior).
RELAY_KEY = os.environ.get("RELAY_ALLOWED_KEY", "").strip()
if RELAY_KEY:
    secret_url = f"https://api.cloudflare.com/client/v4/accounts/{ACCT}/workers/scripts/{SCRIPT_NAME}/secrets"
    sreq = urllib.request.Request(
        secret_url,
        data=json.dumps({"name": "ALLOWED_KEY", "text": RELAY_KEY, "type": "secret_text"}).encode(),
        method="PUT",
    )
    sreq.add_header("X-Auth-Email", EMAIL)
    sreq.add_header("X-Auth-Key", KEY)
    sreq.add_header("Content-Type", "application/json")
    try:
        sresp = urllib.request.urlopen(sreq, timeout=60)
        sdata = json.loads(sresp.read())
        print("SECRET ALLOWED_KEY:", "ok" if sdata.get("success") else json.dumps(sdata.get("errors")))
        sys.exit(0 if sdata.get("success") else 1)
    except urllib.error.HTTPError as exc:
        print("SECRET HTTP ERROR", exc.code)
        print(exc.read().decode(errors="replace")[:500])
        sys.exit(1)
else:
    print("SECRET ALLOWED_KEY: skipped (relay stays open)")
