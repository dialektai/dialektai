# MCP operations reference

**Audience:** pilots running dialekt in production, security
reviewers, future-me debugging an audit-log question at 2 am.

**Status:** v0.20.0.

Companion to `MCP_CLIENT_USAGE.md` (agent-author view) and
`M2_MCP_DESIGN.md` (architecture + decisions).

---

## The audit log

Every MCP-related action writes at least one row to the
`audit_log` table (SQLite, `~/.dialekt/dialekt.db`). The shape is
intentionally **kind-discriminated** so future non-MCP actions
(SQL queries, file operations, lifecycle events) append to the
same table without a schema change.

### Column layout

```sql
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    agent_id    TEXT,               -- NULL for system actions
    binding_id  TEXT,               -- NULL if no binding
    kind        TEXT NOT NULL,      -- event family (see below)
    target      TEXT,               -- server_name for MCP events
    action      TEXT NOT NULL,      -- tool_name for MCP events
    result      TEXT NOT NULL,      -- success | error | timeout | denied | …
    duration_ms INTEGER,
    error_kind  TEXT,               -- NULL when result is success/denied
    extra_json  TEXT                -- JSON payload, shape depends on kind
);
```

Indexes on `ts`, `(agent_id, ts)`, `(kind, ts)` keep common
queries performant once the table grows.

### Event families `kind` can take

| `kind`                   | Who writes it        | `result` values |
|--------------------------|----------------------|-----------------|
| `mcp_tool_call`          | `MCPClientManager`   | `success`, `error`, `timeout`, `server_unavailable`, `rate_limited` |
| `mcp_consent_requested`  | `MCPRuntime`         | `asked` |
| `mcp_consent_decision`   | `MCPRuntime`         | `approved`, `approved_session`, `denied` |

Future M2 Month 2 additions (not shipped in v0.20.0, reserved in
the schema):

| `kind`             | Planned coverage |
|--------------------|------------------|
| `sql_query`        | DialektSQL calls |
| `file_op`          | Filesystem reads/writes |
| `agent_lifecycle`  | Session start/stop |

### `extra_json` by event family

**`mcp_tool_call`**

| Key          | Shape | Notes |
|--------------|-------|-------|
| `consent_id` | int   | Row id of the `mcp_consent_decision` that authorized this call, if any. Missing when no consent was needed (e.g. `autonomy=autonomous`). |

**`mcp_consent_requested`**

| Key                  | Shape | Notes |
|----------------------|-------|-------|
| `server_name`        | str   | Same as `target` — included here for UI rendering. |
| `tool_name`          | str   | Same as `action`. |
| `arguments`          | dict  | Structured args the tool would be called with. May include secrets — consider access control before exposing this column downstream. |
| `destructive`        | bool  | Final determination after annotation + heuristic. |
| `destructive_source` | str   | `"explicit"` (server annotation) or `"heuristic"` (name pattern). |

**`mcp_consent_decision`**

| Key                  | Shape | Notes |
|----------------------|-------|-------|
| `destructive`        | bool  | Mirror of the request field, for standalone queries. |
| `destructive_source` | str   | Same. |

`duration_ms` on decision rows is the time from prompt to
user-click — useful for UX analysis.

### Joining tool calls to their consent

SQL to answer *"was there user consent for this tool call?"*:

```sql
SELECT
    tc.id       AS tool_call_id,
    tc.ts       AS call_ts,
    tc.target   AS server,
    tc.action   AS tool,
    tc.result   AS call_result,
    cd.result   AS consent_result,
    cd.duration_ms AS consent_latency_ms
FROM audit_log tc
LEFT JOIN audit_log cd
    ON cd.kind = 'mcp_consent_decision'
   AND cd.id = json_extract(tc.extra_json, '$.consent_id')
WHERE tc.kind = 'mcp_tool_call'
  AND tc.agent_id = ?
ORDER BY tc.ts DESC;
```

A NULL `consent_result` means the call was dispatched without a
consent prompt — either because the tool is non-destructive or
because `autonomy=autonomous` was configured for that session.

## Known gaps / accepted edge cases

### Rate limit audit is fire-and-forget

When the MCP rate limit trips (60 tool calls per session per
minute, configurable), the audit row is written asynchronously
via `asyncio.create_task`. In a rare shutdown-during-breach
window — the process starting to exit between the breach and the
audit sink completing — the row may not persist.

**Why this is acceptable:**

Rate-limit errors surface to the LLM as `MCPRateLimitError`. The
agent's user sees the outcome; the audit trail for rate limits is
diagnostic, not security-critical. Compare to paths where audit
IS guaranteed:

| Action              | Audit guarantee       |
|---------------------|-----------------------|
| Tool invocation     | `await` — synchronous |
| Consent request     | `await` — synchronous |
| Consent decision    | `await` — synchronous |
| Rate limit breach   | `create_task` — best-effort |

**Future hardening (M3):** if SOC 2 or similar framework requires
guaranteed diagnostic audit, the rate-limit path can be converted
to `await` at the cost of ~10 ms added latency on breach. Low
priority until a compliance audit calls for it.

### Consent prompt `arguments` may contain secrets

The `mcp_consent_requested` row stores the full `arguments` dict
in `extra_json`. If an agent passes a decoded secret value as a
tool argument — say, if it resolves `${secrets.github_token}` and
hands it into a tool call — that value lands in the audit log.

**Mitigations today:**

- `${secrets.*}` substitution happens inside the transport /
  manager layer (env var for stdio, bearer header for HTTP). Tool
  arguments sent by the agent should never reference a resolved
  secret.
- The audit DB is pilot-local (`~/.dialekt/dialekt.db`) and not
  synced to the cloud service. Exposure is the same as any other
  local file.

**Future (M3):** a per-agent "verbose audit" flag can redact
arguments by default and opt in per-session for debugging. Not
shipped in v0.20.0; audit visibility is all-or-nothing.

### Empty `mcp_servers: []` warns, doesn't error

The manifest validator treats an empty `mcp_servers` list as a
warning (code `semantic.mcp_servers_version`) rather than an error.
An omitted field is cleaner; the validator nudges authors toward
that but doesn't reject. If you're running dialekt in strict mode
(`ManifestValidator(strict=True)`) all warnings promote to errors.

## Consent-denial semantics

A user clicking "Deny" is **not an error** — it's the system
doing its job. Consequences:

- `mcp_consent_decision` row has `result="denied"` and
  `error_kind=NULL`. Audit queries that filter on `error_kind IS
  NOT NULL` won't surface denials.
- The agent's code gets a `MCPConsentDenied` exception raised
  through the sync bridge. Agent authors are expected to catch
  this and adapt (propose an alternative, ask the user, give up
  cleanly).
- No `mcp_tool_call` row is written for the denied call; the
  audit trail ends at the decision.

This is the opposite of tool-level errors (`MCPToolError`,
`MCPServerUnavailableError`, etc.) which DO populate
`error_kind` and usually DO produce a `mcp_tool_call` row
(except for server-unavailable before the session opens).

## Managing the sandbox surface

See `M2_MCP_DESIGN.md` Decision 5 for the full security posture.
The salient points for operators:

- stdio subprocesses inherit only a safelist of env vars (PATH,
  HOME, USER, LANG, SHELL, TMPDIR, SYSTEMROOT, …). Manifest env
  and EnvVarsAuth credentials overlay on top.
- Commands are `list[str]`, never strings — no shell
  interpolation.
- Per-call timeout comes from the manifest (default 30 s).
- Per-session rate limit is 60 calls / min.
- Subprocess death fails the next call closed
  (`MCPServerUnavailableError`); no silent restart. A user-
  triggered "restart this server" action is manual today.

## Operational commands

```bash
# How many MCP tool calls did an agent make today?
sqlite3 ~/.dialekt/dialekt.db "
  SELECT target, action, COUNT(*)
  FROM audit_log
  WHERE kind='mcp_tool_call' AND agent_id=? AND ts > datetime('now','-1 day')
  GROUP BY target, action ORDER BY COUNT(*) DESC;"

# Recent denials across all agents
sqlite3 ~/.dialekt/dialekt.db "
  SELECT ts, agent_id, target, action
  FROM audit_log
  WHERE kind='mcp_consent_decision' AND result='denied'
  ORDER BY ts DESC LIMIT 20;"

# Rate-limit trips in the last hour
sqlite3 ~/.dialekt/dialekt.db "
  SELECT agent_id, COUNT(*) AS trips
  FROM audit_log
  WHERE kind='mcp_tool_call' AND result='rate_limited'
    AND ts > datetime('now','-1 hour')
  GROUP BY agent_id;"
```

## Related docs

- `MCP_CLIENT_USAGE.md` — agent-author guide (manifests, consent,
  code patterns).
- `M2_MCP_DESIGN.md` — architectural decisions (7 of them) +
  addenda as they land.
- `TERMINOLOGY_CLARIFICATION.md` — why `python/mcp_servers/` is
  *not* MCP.
- `MCP_RESEARCH_2026-04.md` — ecosystem snapshot at the time of
  Этап 0.
