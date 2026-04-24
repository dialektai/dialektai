# dialekt Manifest Settings — Working Combinations

**Generated:** 2026-04-24
**Validated against:** dialekt v0.10.0 (PR #2 merge)
**Schema version:** `dialekt-manifest-validator` 0.2.0, spec versions `1.0.0` and `1.0.1` accepted

This is a **pilot-facing** reference. It answers: "if I design my own agent, which manifest field combinations will actually work?" Developer-level coverage lives in [`CAPABILITIES_INVENTORY.md`](CAPABILITIES_INVENTORY.md) and [`SETTINGS_COVERAGE.md`](SETTINGS_COVERAGE.md).

---

## 1. Manifest field reference

### Top-level envelope

| Field | Working values | Default / notes |
|---|---|---|
| `spec_version` | `1.0.1`, `1.0.0` | Accepted by validator. Use `1.0.1`. |
| `minimum_dialekt_version` | any semver ≤ current app | Advisory today; not enforced at runtime. Use `1.0.0`. |

### `metadata` (all required)

| Field | Notes |
|---|---|
| `id` | Must be a UUID v4. Generate with `python3 -c "import uuid; print(uuid.uuid4())"`. |
| `name`, `description`, `version` | Free text. Version should be semver. |
| `language` | One of `en`, `ru`, `kk`, `multi`. Kazakh (`kk`) added in F-A4. |
| `tags` | Free-form list of strings. |
| `author.name`, `author.email` | Both required. |
| `created_at`, `updated_at` | ISO-8601 timestamps. Required by validator. |

### `model`

| Field | Working values |
|---|---|
| `preferred` | Any Ollama model tag installed locally. Family-match fallback applies if exact is missing. |
| `acceptable` | Array of fallback models tried in order. |
| `min_context_window` | Int (e.g. `8192`, `32768`). Advisory. |
| `requirements.min_ram_gb` / `min_vram_gb` / `recommended_ram_gb` | Advisory — logged but does not block. |
| `parameters.temperature` / `top_p` / `max_tokens` | Accepted by schema. **Runtime currently ignores these** — global Settings → Performance wins. Leave placeholder values or set to your preference; treat it as documentation for now. |

### `autonomy`

| Field | Working values | Behaviour |
|---|---|---|
| `recommended` | `review-only`, `ask-before-write`, `autonomous`, `sandbox-only`, `manual` | Default behaviour on agent open. `manual` added in F-A1. |
| `max_allowed` | Same set | Schema-level ceiling. **Runtime does not enforce `max_allowed` as an upper bound on the per-session slider today** — it's documentation. |

### `capabilities.groups`

Exactly 8 values are schema-valid:

`filesystem_read`, `filesystem_write`, `database_read`, `database_write`, `shell_execute`, `network`, `browser`, `screen_capture`.

Any other string (e.g. `filesystem`, `terminal`, `screen`) fails validation — see `F-A1` / `F-A5` history.

**Runtime reality:** these are advisory metadata today. The actual gate for what code an agent can run is `autonomy.recommended` + global Settings → Permissions. The capabilities list is what pilots should read to understand a published agent, not a sandbox boundary.

### `connections.required[*]`

| Field | Working values | Runtime support |
|---|---|---|
| `type` | `postgres`, `mysql`, `clickhouse`, `mcp-server`, `http-api` | **Only `postgres`, `mysql`, `clickhouse`** have backend routers. `mcp-server` and `http-api` pass validation but bind nowhere. |
| `role` | `admin`, `readonly`, `readwrite` | `readonly` is the one we actually consume. Others are advisory. |
| `database_category` | `warehouse`, `reporting`, `transactional`, `analytics`, `operational` | Advisory metadata. Used by wizard to suggest defaults. |
| `required_permissions` | Free-form list | Advisory. |

### `variables[name]`

| Field | Working values |
|---|---|
| `type` | `string`, `number`, `boolean`, `list` |
| `required` | `true` / `false` |
| `description` | Free text |
| `default` | Type must match `type`. |

**Important:** only `{{connection_id}}`, `{{connection_name}}`, and `{{database_type}}` are substituted into the system prompt by dialekt today. Custom variables pass validation but **the UI does not prompt the user for them** and **the runtime does not substitute them** into the prompt. Plan custom variables for M2.

### `trigger`

| Value | Runtime support |
|---|---|
| `type: interactive` | ✅ Working (this is the chat flow). |
| `type: scheduled` (with `cron`, `timezone`, `missed_run_policy` ∈ {`skip`, `run_on_startup`}) | ❌ Schema-valid; no scheduler process exists. Agent will validate, import, but never fire. |
| `type: webhook` | ❌ Not a schema variant. |

### `input`

| Field | Working values | Runtime |
|---|---|---|
| `type` | `chat` (the only one the UI renders) | ✅ |
| `type: form` | schema-valid, no UI | ❌ |
| `type: none` | schema-valid, no UI | ❌ |

### `output`

| Field | Working values | Runtime |
|---|---|---|
| `format` | `markdown`, `table` | ✅ |
| `format: json` / `file` / `image` | schema-valid, not rendered differently today | ⚠️ |
| `streaming` | `true`, `false` | ✅ streaming is the WebSocket path. |
| `destination.type` | `notification` | ✅ (renders in the chat column). |
| `destination.type: filesystem` / `webhook` / `email_or_telegram` | ❌ Schema-valid, no delivery runtime. |

---

## 2. Combinations validated end-to-end in [AGENT_CATALOG.md](AGENT_CATALOG.md)

Each of the following combinations was exercised on v0.10.0 with a live chat turn:

| Combination | Catalog entry | Verified |
|---|---|---|
| `postgres` + `database_read` + `ask-before-write` + RU/EN prompt | 1.1 PG Sales Analyst | ✅ |
| `mysql` + `database_read` + `ask-before-write` + EN prompt | 1.2 MySQL Inventory Analyst | ✅ |
| `clickhouse` + `database_read` + `ask-before-write` + EN prompt | 1.3 ClickHouse Events Analyst | ✅ |
| `filesystem_read` + code-focused prompt + qwen2.5-coder model | 2.1 Python Code Reviewer | ✅ |
| `shell_execute` + `review-only` autonomy | 2.2 Bash Script Helper | ✅ |
| No caps, no conns, `multi` language | 3.1 Document Summarizer | ✅ |
| No caps, `language: kk` | 3.2 Translator RU-EN-KK | ✅ |
| Bundled General Assistant (full surface, `published`) | 4.1 General Assistant | ✅ |
| No caps, `language: ru` | 4.2 Russian Writing Assistant | ✅ |
| `database_read` + `filesystem_read` + `shell_execute` + PG connection + two variables (`string`, `string`) | 5.1 Data Engineer Helper | ✅ |

---

## 3. Combinations that fail or are silently no-ops

If you write any of these into a manifest, the validator may accept it, but nothing will fire at runtime. Do not promise them to pilots.

| Combination | Symptom | Target fix |
|---|---|---|
| `trigger.type: scheduled` | Imports, visible in agent list, **never runs** — no cron runtime. | M2 (Q3 2026) |
| `trigger.type: webhook` | Validation error — not a schema variant. | M3 |
| `connections.required[*].type: mcp-server` | Validates. Binding UI can't pick it. Runtime has no router. | M2 |
| `connections.required[*].type: http-api` | Same as above. | M2 |
| `output.destination.type: email_or_telegram` | Validates. No SMTP / Telegram transport. | M2 |
| `output.destination.type: filesystem` | Validates. No writer. | M2 |
| `output.destination.type: webhook` | Validates. No HTTP POST runtime. | M2 |
| Custom `variables` beyond `connection_id` | Validates. UI never asks the user for the value. Runtime leaves `{{my_var}}` literal in the prompt. | M2 |
| `secrets_required: [...]` | Validates. No UI to supply the secret; runtime does not read it. | M2 |
| `model.parameters.temperature` / `max_tokens` | Validates. Runtime ignores these — global Settings → Performance wins. | M2 |
| `autonomy.max_allowed` as a ceiling | Validates. Runtime slider is not actually capped by this value today. | M2 |
| `input.type: form` or `none` | Validates. UI only renders `chat`. | M2 |

---

## 4. Manifest authoring checklist

When writing a new manifest for a pilot, verify:

1. Every value in `capabilities.groups` is one of the 8 valid names above. Common typos caught by the validator: `filesystem` (use `filesystem_read`/`filesystem_write`), `terminal` (use `shell_execute`), `screen` (use `screen_capture`).
2. `metadata.id` is UUID v4.
3. `metadata.created_at` and `updated_at` are set (ISO-8601).
4. `model.min_context_window`, `model.requirements`, `model.parameters` are all present (the validator requires them even if the runtime ignores the parameters).
5. `trigger`, `input`, `output` are all present (3 required envelope fields that are easy to forget — see F-A1 history).
6. Only `postgres`, `mysql`, or `clickhouse` appear in `connections.required[*].type`.
7. If you use `{{var}}` in the system prompt, the only ones substituted today are `{{connection_id}}`, `{{connection_name}}`, `{{database_type}}`.

Validate locally before shipping:

```bash
dialekt-manifest-validate my-agent.yaml
# or, from within the repo:
python -c "from dialekt_manifest import ManifestValidator; \
  r = ManifestValidator().validate_string(open('my-agent.yaml').read()); \
  print('OK' if r.valid else r.errors)"
```

---

**See also:**
- [`AGENT_CATALOG.md`](AGENT_CATALOG.md) — working agent configurations you can copy and tweak
- [`TOOLS_AVAILABLE_TODAY.md`](TOOLS_AVAILABLE_TODAY.md) — what an agent's code can actually call
- [`CAPABILITIES_STATUS.md`](CAPABILITIES_STATUS.md) — developer-level per-capability status
