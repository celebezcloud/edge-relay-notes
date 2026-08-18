#!/usr/bin/env python3
"""Verify the relay end-to-end the same way Hermes calls it: OpenAI SDK + streaming.

Streaming is the real test — a plain non-stream curl can pass while streaming
fails (see docs/03-troubleshooting.md, `data: null` SSE bug).

    export AGENTROUTER_KEY="sk-..."      # or leave unset to read ~/.hermes/.env
    export RELAY_BASE_URL="https://my-relay.YOUR_SUBDOMAIN.workers.dev/v1"
    python3 scripts/verify.py
"""
import os
import pathlib
import sys

try:
    from openai import OpenAI
except ImportError:
    sys.exit("pip install openai")

ENV_KEY = "HERMES_CUSTOM_AGENTROUTER_ORG_API_KEY"
key = os.environ.get("AGENTROUTER_KEY") or os.environ.get(ENV_KEY)
if not key:
    env_path = pathlib.Path.home() / ".hermes" / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{ENV_KEY}="):
                key = line.split("=", 1)[1].strip().strip("\"'")
                break
if not key:
    sys.exit(f"No API key. Set AGENTROUTER_KEY or {ENV_KEY} in ~/.hermes/.env")

base_url = os.environ.get("RELAY_BASE_URL")
if not base_url:
    sys.exit("Set RELAY_BASE_URL ke URL Worker relay-mu, mis. https://my-relay.YOUR_SUBDOMAIN.workers.dev/v1")
models = os.environ.get("RELAY_MODELS", "claude-opus-4-8,claude-opus-5,gpt-5.6-sol").split(",")

client = OpenAI(api_key=key, base_url=base_url, timeout=90,
                default_headers={"User-Agent": "Mozilla/5.0"})

failed = False
for model in [m.strip() for m in models if m.strip()]:
    parts, chunks = [], 0
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply exactly OK"}],
            max_tokens=50,
            stream=True,
        )
        for chunk in stream:
            chunks += 1
            if chunk.choices and chunk.choices[0].delta.content:
                parts.append(chunk.choices[0].delta.content)
        text = "".join(parts)
        ok = "OK" in text
        print(f"{model:20s} {'STREAM_OK ' if ok else 'STREAM_EMPTY'} chunks={chunks} content={text!r}")
        failed = failed or not ok
    except Exception as exc:  # noqa: BLE001 - report any provider failure verbatim
        failed = True
        print(f"{model:20s} STREAM_FAIL {type(exc).__name__}: {str(exc)[:200]}")

print("\nRESULT:", "FAIL" if failed else "ALL_OK")
sys.exit(1 if failed else 0)
