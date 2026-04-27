# GPU Relay — Cloud-Assisted Tier

Pilots without a discrete GPU can route their Ollama inference through
the dialekt server (`gpu-relay.dias.now` → RTX 3060 in Almaty, KZ).
Stateless proxy: only token counts and timestamps are persisted; no
prompts, no responses, no derived embeddings. A pilot's data path
never leaves Kazakhstan.

## Why this exists

- **Hardware**: a meaningful slice of pilots run dialekt on laptops
  without GPUs. Local-only inference is too slow to be useful for
  agentic workflows on those machines.
- **Compliance**: Kazakhstan's data-protection law (закон о ПДн,
  effective 2026-01-18) requires that personal data of KZ residents
  be processed on infrastructure physically located in KZ. SaaS LLMs
  (OpenAI, Anthropic, Gemini) violate this for regulated tenants.
- **Stateless by design**: the relay never persists prompt or response
  bodies. The only writes to the database are billing rows
  `(tenant_id, relay_key_id, model, prompt_tokens, completion_tokens,
  latency_ms, created_at)` — the same shape an audit team can hand to
  a regulator without redaction.

The relay is *transport*, not a SaaS LLM. The model runs on a single
GPU in Almaty; the customer's tenant authenticates against it; usage
is billed at a flat seat price.

## Architecture

```
┌────────────────────────────────────────────┐
│  Pilot laptop (no GPU)                     │
│   dialekt desktop  (Tauri + sidecar :8765) │
│        │                                   │
│        └─ PluginContext (relay mode)       │
│              ▼                             │
│        ~/.dialekt/relay.toml               │
└────────────────────────────────────────────┘
                 │  HTTPS  Bearer dlk_relay_…
                 ▼
       gpu-relay.dias.now  (Cloudflare tunnel)
                 │
                 ▼
        nginx → 127.0.0.1:3050   (FastAPI relay)
                 │
                 ├─ verify Bearer (asyncpg → dialekt_cloud.relay_keys)
                 ├─ rate-limit (RateLimiterRegistry, rolling 60s)
                 ├─ proxy → http://127.0.0.1:11434  (Ollama on RTX 3060)
                 └─ on terminal NDJSON chunk:
                       INSERT relay_usage (tokens, latency)
```

Two parallel route surfaces, same auth + billing chain:

| Path                  | Ollama target           | Notes |
|-----------------------|-------------------------|-------|
| `GET  /relay/health`  | reachability + Ollama probe | unauthenticated |
| `GET  /relay/models`  | `GET /api/tags`         | |
| `POST /relay/generate`| `POST /api/generate`    | streamed pass-through |
| `POST /relay/chat`    | `POST /api/chat`        | streamed pass-through |
| `POST /relay/embed`   | `POST /api/embed`       | |
| `POST /relay/embeddings` | `POST /api/embeddings` | legacy single-input |
| `GET  /api/tags`      | `GET /api/tags`         | drop-in alias |
| `POST /api/chat`      | `POST /api/chat`        | drop-in alias for litellm |
| `POST /api/generate`  | `POST /api/generate`    | drop-in alias |
| `POST /api/embed`     | `POST /api/embed`       | drop-in alias |
| `POST /api/embeddings`| `POST /api/embeddings`  | drop-in alias |

The `/api/*` aliases let any Ollama client (litellm, raw httpx,
LangChain ollama provider) point its `base_url` at the relay and have
everything work without path translation. The `/relay/*` paths are
preserved for explicit relay-aware tooling.

## What is and isn't logged

**Logged** (table `relay_usage`):
- tenant id, relay-key id
- model name (e.g. `llama3:8b`)
- prompt token count
- completion token count
- latency in milliseconds
- timestamp

**Not logged**:
- prompt text
- response text
- system prompts
- tool call arguments
- agent manifests
- embeddings produced

The relay's HTTP request handler holds the buffered request/response
bytes only for the lifetime of one HTTP transaction. Nothing is
written to disk, nothing is forwarded to an audit log, nothing is
indexed. After the connection closes, the bytes are released by the
garbage collector.

## Founder admin guide — issue a key

Authenticate to the dialekt-cloud admin panel (`/admin/ui`). Then:

```bash
curl -X POST https://api.dias.now/admin/tenants/$TENANT_ID/relay-keys \
     -H "Authorization: Bearer $ADMIN_SESSION_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name": "ACME corp - pilot laptop",
          "rate_limit_per_minute": 120,
          "monthly_token_quota": null}'
```

Response includes `plaintext` — the actual `dlk_relay_<token>` Bearer.
**Copy it now.** The plaintext is never re-readable; only the SHA-256
hash hits the database. If the customer loses the key, revoke and
re-issue.

```bash
# List active keys for a tenant:
curl https://api.dias.now/admin/tenants/$TENANT_ID/relay-keys \
     -H "Authorization: Bearer $ADMIN_SESSION_TOKEN"

# Revoke a key:
curl -X DELETE https://api.dias.now/admin/relay-keys/$KEY_ID \
     -H "Authorization: Bearer $ADMIN_SESSION_TOKEN"

# Daily usage rollup (last 30 days):
curl https://api.dias.now/admin/tenants/$TENANT_ID/relay-usage \
     -H "Authorization: Bearer $ADMIN_SESSION_TOKEN"
```

Cloud-Assisted tier is **+$10 / seat / month** on top of the base
license. Tenant.plan field carries the standard `team` / `solo`
value; the Cloud-Assisted line item is invoiced separately.

## Pilot guide — turn on Cloud GPU

1. Open dialekt → **Settings → Models**.
2. Top of the screen: **Inference location**. Click **CLOUD GPU**.
3. URL is pre-filled (`https://gpu-relay.dias.now`). Don't change
   unless support tells you to.
4. Paste the `dlk_relay_…` key your admin sent you.
5. Click **Test connection**. Toast should report `auth ✓` within a
   second or two.
6. Click **Save**. Done — every chat from this point onwards runs on
   the relay.

Switching back to local: same screen, click **LOCAL**. The relay key
stays saved (so you can flip back without re-pasting), but inference
flows through your local Ollama again.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `Test connection` says **network error** | DNS / firewall blocking `gpu-relay.dias.now`. Check from a browser: `https://gpu-relay.dias.now/relay/health` should return JSON. |
| `Test connection` says **key invalid or revoked** | Admin revoked the key, or there's a typo. Ask admin to re-issue. |
| Chat hangs on first message | Cold-start the relay's Ollama. `Test connection` reports `Ollama down` — operator-side issue, not yours. |
| 429 in the log when chat fires | Rate limit (default 120/min/key). Admin can raise the per-key cap. |
| 503 from `/relay/*` | Relay started without `cloud_db_url` configured — operator misconfiguration. |

## Operator runbook

### nginx server block (`/etc/nginx/sites-enabled/projects`)

```nginx
server {
    listen 80;
    server_name gpu-relay.dias.now;

    proxy_buffering off;          # streaming — bytes flow as they arrive
    proxy_read_timeout 3600;      # large generations on small models
    proxy_request_buffering off;  # let the relay see chunks as they come

    location / {
        proxy_pass http://127.0.0.1:3050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
    }
}
```

`sudo nginx -t && sudo nginx -s reload`.

### Cloudflare tunnel route

```bash
cloudflared tunnel route dns f062be49-215f-4c56-9b52-242352b6480e gpu-relay.dias.now
```

### Process supervision (pm2)

`~/.dialekt/relay-server.toml`:

```toml
[server]
port = 3050
ollama_url = "http://127.0.0.1:11434"
cloud_db_url = "postgres://USER:PASS@127.0.0.1:5432/dialekt_cloud"
log_level = "INFO"
default_rate_limit_per_minute = 120
```

```bash
pm2 start --name relay-server \
    --interpreter $(which python) \
    -- -m dialekt.relay
pm2 save
```

### Smoke test from outside

```bash
# Health (no auth required)
curl --doh-url https://cloudflare-dns.com/dns-query \
     https://gpu-relay.dias.now/relay/health
# → {"ok":true,"version":"0.1.0","ollama_reachable":true}

# Models (auth required)
curl --doh-url https://cloudflare-dns.com/dns-query \
     -H "Authorization: Bearer dlk_relay_…" \
     https://gpu-relay.dias.now/relay/models
```

### Inspecting usage

```sql
SELECT
  date_trunc('day', created_at)::date AS day,
  count(*)                 AS requests,
  sum(prompt_tokens)       AS prompt_tokens,
  sum(completion_tokens)   AS completion_tokens,
  avg(latency_ms)::int     AS avg_latency_ms
FROM relay_usage
WHERE tenant_id = '…'
  AND created_at >= now() - interval '30 days'
GROUP BY day
ORDER BY day DESC;
```

The same query is exposed via
`GET /admin/tenants/{id}/relay-usage?days=N`.

### Common config questions

- **Q: Can a tenant use multiple keys?** Yes — each pilot laptop in a
  team can have its own key, scoped to the same tenant for billing.
- **Q: Can keys be scoped to specific models?** Not in this version;
  per-key allow-listing is a follow-up.
- **Q: What happens if the GPU is offline?** `/relay/health` reports
  `ollama_reachable: false`. Authenticated calls fail with 502 and no
  billing row is written.

## File map

- Relay process: `python/dialekt/relay/{server,auth,billing,config}.py`
- Desktop sidecar config endpoints: `python/server.py` (search "GPU Relay")
- Desktop UI: `frontend/src/screens/SettingsScreen.jsx` →
  `RelayLocationCard`
- PluginContext + resolver: `python/dialekt/llm/_plugin_context.py`,
  `python/dialekt/llm/resolver.py`,
  `python/dialekt/llm/few_shot_memory.py`
- Cloud schema + admin: `dialekt-cloud/src/dialekt_cloud/db.py`,
  `dialekt-cloud/src/dialekt_cloud/services/relay_keys.py`,
  `dialekt-cloud/src/dialekt_cloud/routers/admin.py`
