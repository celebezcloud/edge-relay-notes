# Konfigurasi Hermes Agent

## 1. API key (env)

Tambahkan ke `~/.hermes/.env`:

```bash
HERMES_CUSTOM_AGENTROUTER_ORG_API_KEY=sk-xxx
```

Key dibaca via `key_env` — **jangan** taruh key mentah di `config.yaml`.

## 2. Custom provider

Blok di `~/.hermes/config.yaml` → `custom_providers` (ini persis konfigurasi yang live & terverifikasi):

```yaml
- name: Agentrouter.org
  base_url: https://my-relay.YOUR_SUBDOMAIN.workers.dev/v1   # URL Worker relay
  key_env: HERMES_CUSTOM_AGENTROUTER_ORG_API_KEY
  model: claude-opus-4-8
  api_mode: chat_completions
  discover_models: false
  models:
    claude-opus-4-8:
      context_length: 1000000
    claude-opus-5:
      context_length: 1000000
    gpt-5.6-sol:
      context_length: 1000000
```

Catatan penting:
- `base_url` **harus** URL Worker relay (`*.workers.dev/v1`), bukan `https://agentrouter.org/v1` langsung — direct kena WAF 405 dari VPS.
- `api_mode: chat_completions` — format OpenAI. **Jangan** `anthropic_messages` kalau `base_url` sudah berakhiran `/v1` (jadi `/v1/v1/messages`).
- `discover_models: false` — endpoint `/v1/models` backend bisa menolak (403), jadi daftar model ditulis manual.

> `config.yaml` write-protected dari edit tool agent. Untuk ubah nilai sederhana pakai `hermes config set <key> <value>`; untuk sisipkan blok, edit lewat shell dengan hati-hati.

## 3. Context 1M — override per-model (bukan global!)

**Pola yang benar** — hanya model yang disebut yang terpengaruh:

```yaml
models:
  gpt-5.6-sol:
    context_length: 1000000   # 1M = 1000000, integer polos (bukan "1M"/"1000K")
```

**Jangan** pakai global `model.context_length` — itu membekukan context **semua** model di satu angka dan bisa merusak model lain yang kapasitasnya lebih kecil.

Model yang sudah di-set 1M (18 Agu 2026):

| Provider | Model | Context |
|---|---|---|
| Agentrouter.org | claude-opus-4-8 | 1.000.000 |
| Agentrouter.org | claude-opus-5 | 1.000.000 |
| Agentrouter.org | gpt-5.6-sol | 1.000.000 |
| b.ai | deepseek-v4-flash | 1.000.000 |

## 4. Validasi

```bash
hermes config check                  # YAML valid, tanpa error
hermes config get custom_providers   # cek override terbaca
python3 scripts/verify.py            # end-to-end streaming → ALL_OK
```

Perubahan `config.yaml` terbaca **live** oleh gateway (cache mtime+size) — **tidak perlu restart** gateway untuk provider/model baru.

Hasil verifikasi terakhir (18 Agu 2026):
```
claude-opus-4-8      STREAM_OK  chunks=5 content='OK'
claude-opus-5        STREAM_OK  chunks=5 content='OK'
gpt-5.6-sol          STREAM_OK  chunks=3 content='OK'
RESULT: ALL_OK
```

## 5. Ganti model aktif

```bash
hermes model    # pilih provider + model secara interaktif
```

atau `/model` di chat. Setelah switch, context diambil dari override di config.

## 6. Gotcha `model.default`

`model.default` **wajib** model yang tersedia di base_url default (`api.tokenrouter.com/v1`). Menaruh model yang cuma ada di custom provider sebagai `model.default` bikin semua chat error `503 No available channel`. Ganti model aktif lewat `/model`, bukan dengan mengubah `model.default`.
