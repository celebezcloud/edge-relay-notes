# Deploy Cloudflare Worker Relay

Worker ini meneruskan **semua** request ke `https://agentrouter.org` dari egress IP Cloudflare, membersihkan header CF, menyuntikkan header spoof Claude Code, dan memfilter baris SSE `data: null` yang merusak streaming.

## Opsi A — Script (direkomendasikan)

```bash
export CF_EMAIL="you@example.com"
export CF_API_KEY="cfk_..."      # Global API Key (X-Auth-Email + X-Auth-Key)
export CF_ACCOUNT_ID="YOUR_CF_ACCOUNT_ID"
export WORKER_NAME="my-relay" # opsional, default my-relay

python3 scripts/deploy.py
# HTTP 200
# { "success": true, "result_id": "my-relay", "errors": [] }
```

Script pakai `urllib` (stdlib) — tidak butuh wrangler, node, atau npm.

## Opsi B — Dashboard Cloudflare (manual)

1. Login [dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages** → **Create** → **Worker**.
2. Nama worker: `my-relay` (bebas, tapi harus konsisten dengan `base_url` di config Hermes).
3. Hapus template bawaan, paste seluruh isi `worker.js`, klik **Deploy**.
4. Catat URL: `https://my-relay.<subdomain>.workers.dev`.

## Opsi C — curl manual

```bash
# Upload script (multipart, ES module format WAJIB)
curl -X PUT \
  "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/workers/scripts/my-relay" \
  -H "X-Auth-Email: $CF_EMAIL" \
  -H "X-Auth-Key: $CF_API_KEY" \
  -F 'metadata={"main_module":"index.js","compatibility_date":"2024-09-25"};type=application/json' \
  -F 'index.js=@worker.js;type=application/javascript+module'

# Aktifkan route di subdomain workers.dev
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/workers/scripts/my-relay/subdomain" \
  -H "X-Auth-Email: $CF_EMAIL" -H "X-Auth-Key: $CF_API_KEY" \
  -H "Content-Type: application/json" -d '{"enabled":true}'
```

**Wajib `main_module` + `application/javascript+module`** — worker pakai format ES module (`export default { fetch }`). Kalau pakai `body_part`/`application/javascript` (service-worker format), deploy akan gagal atau worker error saat runtime.

## Verifikasi

```bash
# 1. Health check — worker v5: retry 5xx + auth gate (spoof: "v5")
curl https://my-relay.<subdomain>.workers.dev/health
# → {"status":"ok","proxy":"agentrouter","spoof":"v5","retries":2}

# 2. End-to-end + streaming (test yang benar-benar penting)
python3 scripts/verify.py
# → claude-opus-4-8   STREAM_OK  chunks=N content='OK'
#   RESULT: ALL_OK
```

Non-stream curl bisa lulus sementara streaming gagal — **selalu** verifikasi dengan streaming (`scripts/verify.py`), karena Hermes memakai stream.

## Ambil source worker yang sedang live

```bash
curl "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/workers/scripts/my-relay" \
  -H "X-Auth-Email: $CF_EMAIL" -H "X-Auth-Key: $CF_API_KEY" -o live-worker.js
```

Respons berupa envelope multipart — buang baris header/boundary di awal dan akhir untuk mendapat JS bersih.

## Catatan worker (v5)

- **Auth gate (v5)**: saat deploy dengan `RELAY_ALLOWED_KEY` di-set, worker hanya melayani `Authorization: Bearer <key>` yang cocok (disimpan sebagai secret `ALLOWED_KEY`). Request lain → `401 relay_auth_error` tanpa memanggil upstream. Ini mengunci relay: URL yang bocor atau repo yang di-copy tidak berguna tanpa key. Tanpa secret, relay tetap terbuka (legacy).
- **Retry transient**: worker menyerap `429` (AWS Bedrock rate limit), `500` (channel flap `无可用渠道`), `502/503`, dan `504` (origin lambat) dengan maksimal 3 attempt + backoff (1s/2s, hormati `Retry-After` dibatasi 3s). Body di-buffer supaya POST bisa dikirim ulang; respons diteruskan dengan header `X-AgentRouter-Retries`.
- **Guardrail konten TIDAK di-retry**: `500 sensitive words detected` / `content-blocked` bersifat deterministik (konten sama → filter sama), jadi relay langsung meneruskannya tanpa buang waktu retry. Detail: `03-troubleshooting.md` §4.
- **Tidak ada filter konten di worker** — murni relay. Semua blokir konten (`sensitive words detected`, `content-blocked`) datang dari backend `agentrouter.org`.
- Header yang di-spoof: `User-Agent: claude-cli/2.1.92`, `Anthropic-Version`, `Anthropic-Beta`, `Anthropic-Dangerous-Direct-Browser-Access`, `X-App`, `X-Stainless-*`.
- Worker menghapus `cf-connecting-ip`, `cf-ray`, `x-forwarded-for`, `x-real-ip` dll. agar IP client tidak bocor ke origin.
- Response `content-encoding` / `content-length` / `transfer-encoding` dihapus supaya body tidak dobel-encode.
- SSE (`text/event-stream`) dilewatkan `TransformStream` yang membuang baris `data: null` — lihat `03-troubleshooting.md` §5.
