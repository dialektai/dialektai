# v0.26 — MCP Process Resilience (Design Doc)

**Status:** v1 APPROVED by mentor (pass 1) on 2026-04-25. Two P1 findings
inlined below: (a) registry concurrency posture documented, (b) callback
failure isolation pytest elevated from optional to required.

## Goal

Detect when a stdio MCP child process dies mid-session and **surface the
crash to pilots in the UI** so they aren't surprised by silent failures.

**Explicitly NOT in scope** (mentor pass-1 ruling for v0.26):
- ❌ Auto-restart (requires answering "what does the consent state
  machine do when a server respawns mid-session" — separate v0.27+
  ruling)
- ❌ Refactoring `MCPClientManager._clients` (use a sibling registry)
- ❌ Health probes / heartbeat polling against running children
- ❌ Tool error retry (that's #3 in v0.27, depends on #2 landing first)

## Today's behaviour (grounding)

`MCPClientManager._clients: dict[str, MCPClient]` caches one client per
configured MCP server (manager.py:83). Each stdio client wraps an
`mcp.client.stdio.stdio_client` async context manager → child process.
The cache is opened lazily on first `call_tool` (`get_client`,
manager.py:90-110).

When a child dies between calls:
1. The next `call_tool` calls `client.send_request` against a broken
   pipe → `BaseException` caught at manager.py:178-187 → classified by
   `classify_sdk_error` to `MCPServerUnavailableError` →
   `mcp_tool_call.result = "server_unavailable"` audit row written.
2. The dead client stays in `_clients` until `shutdown()` or eviction.
3. **Nothing surfaces to the UI**. The Settings → MCP Servers list shows
   the row's old `last_test_ok` value (last manual `[Test]` outcome).
   A pilot trying that server in chat just sees "tool call failed."

DB schema:
```
mcp_servers (
    id, name, transport, command_json, ...,
    last_test_at, last_test_ok, last_test_error, tool_count,
    updated_at, created_at
)
```

`POST /mcp-servers/{id}/test` updates `last_test_*` for a manual probe.
`GET /mcp-servers` returns the row including those fields. UI already
renders a red status dot when `last_test_ok=0`.

## Proposed design (sibling registry, reactive detection)

### Module: `dialekt/mcp/health.py` (new)

```python
class MCPHealthRegistry:
    """In-memory observer of MCPClientManager call outcomes. Sibling
    to the cache, not a rewrite. Single registry per process."""

    def __init__(self, persist_callback): ...
    async def mark_healthy(self, server_name: str) -> None: ...
    async def mark_crashed(self, server_name: str, error: str) -> None: ...
    def status(self, server_name: str) -> Optional[HealthRow]: ...
```

`HealthRow`: simple dataclass — `status: Literal["healthy", "crashed"]`,
`error: Optional[str]`, `since: datetime`.

**Concurrency (P1, mentor pass 1):** the registry is per-process; multiple
`MCPClientManager` instances (one per agent session) may call into it
concurrently from the same asyncio loop. `mark_*` methods are pure-sync
state mutations on an internal dict — guarded by an `asyncio.Lock` for
write-side serialization with the persist callback. Reads are lock-free
(dict snapshots). The registry assumes single-event-loop cooperative
concurrency; thread-pool callers must shim through `loop.call_soon_threadsafe`.

### Wire-in: `MCPClientManager.call_tool` (existing)

At manager.py around line 180 (the BaseException classifier):
- On `MCPServerUnavailableError` → `health.mark_crashed(server_name, error_kind)`
- On `success` result → `health.mark_healthy(server_name)`
- The mark calls **never raise** — health-tracking failures must not
  break tool execution.

### Persistence callback

`MCPHealthRegistry` is in-memory, but every state transition fires a
callback that writes to `mcp_servers` row:
- `mark_crashed` → `last_test_ok = 0`, `last_test_error = "live: " +
  error_kind`, `last_test_at = NOW`
- `mark_healthy` → only if previous status was `crashed` (don't
  overwrite a clean manual `[Test]` result with a redundant healthy
  ping)

Callback is async, fired in a background task so DB I/O doesn't block
the call path.

### UI surface

**Zero new endpoint**, zero new column. The existing `GET /mcp-servers`
list already returns `last_test_ok` + `last_test_error`. The `live: `
prefix on `last_test_error` lets the UI distinguish a runtime crash
from a manual-test failure if it wants to (purely cosmetic — both render
as the same red dot today).

Optional: add a small `live_status: "healthy" | "crashed" | "unknown"`
field to the response, computed from the in-memory registry. Only
``unknown`` for servers that haven't been called in this process
lifetime. Surface as a small `(crashed)` annotation in the MCP Servers
list row.

## Open questions for mentor's first pass

1. **Detection mechanism.** Recommend reactive (catch
   `MCPServerUnavailableError` at the manager call path). Alternative:
   spawn a background task to `proc.poll()` every ~5s on each cached
   client. Reactive is cheaper (zero idle work) and matches "narrow"
   scope. Want APPROVE.
2. **Storage strategy.** Recommend reuse `mcp_servers.last_test_*` with
   a `live: ` prefix on the error string — no schema migration. Cleaner
   alternative: add a `live_status` column. Want ruling.
3. **In-memory `live_status` field on GET /mcp-servers.** Want APPROVE
   on adding this small computed field (5-10 LOC), so the UI can
   render `(crashed)` next to the row name.
4. **Reset rule.** Recommend: `mark_crashed` always wins; `mark_healthy`
   only clears a previous crashed state (never overwrites a clean
   manual-test success). Manual `[Test]` re-running re-asserts the row
   normally and will clear the crash if the server is back.
5. **HTTP transport.** Currently no analogous "process death" — it's
   request/response. Should HTTP servers participate in the registry at
   all? Recommend: yes for symmetry — HTTP `MCPServerUnavailableError`
   (e.g., 503 / connection refused) flips to crashed too.

   **Flicker note (mentor P2):** First HTTP `MCPServerUnavailableError`
   flips to `crashed`; the next successful call clears. Pilots may see
   brief crashed states on transient network issues — accepted for v0.26,
   revisit in v0.27 retry policy when the transient/durable distinction
   is needed. Stdio process death is durable; HTTP is request-scoped and
   transient — registry doesn't model this distinction yet.

## Non-goals (explicit)

- ❌ Auto-restart of dead children
- ❌ Periodic heartbeat / ping
- ❌ Subprocess exit-code observation (we infer from call failure, not
  from `proc.wait()`)
- ❌ Multi-tenant scoping — single-tenant desktop today
- ❌ Cross-process registry (cloud) — desktop-local only
- ❌ Notifying chat sessions in flight (the call already raises
  `MCPServerUnavailableError` and the audit row reflects that — UI
  surfacing is for the **next** chat turn / Settings glance)
- ❌ #3 retry policy — **next release**

## LOC budget

Mentor pass-1 brief: ~200-300 LOC.

| Slice                                | LOC   |
|--------------------------------------|-------|
| `dialekt/mcp/health.py` (new module) | ~70   |
| Wire into manager.py call path       | ~15   |
| Persistence callback in server.py    | ~25   |
| `live_status` field in /mcp-servers  | ~10   |
| Pytest                               | ~80   |
| **Subtotal**                         | ~200  |
| Frontend `(crashed)` annotation      | ~15   |
| **Total**                            | ~215  |

**Mid-brake at 270 LOC backend (≤300 mentor ceiling).** If we breach,
**stop**, ship without the `live_status` field (UI gets crash signal via
the existing `last_test_ok` red dot only), **re-invoke mentor before
continuing** (per discipline §2).

## Commit ordering

1. **Health registry module + manager wire-in + pytest** — ~165 LOC.
   Adds `dialekt/mcp/health.py`, calls into the registry from
   `MCPClientManager.call_tool` for both success and
   `MCPServerUnavailableError`. **Required tests** (mentor pass 1
   elevation — these are P1, not optional):
   - clean cycle: healthy → crashed → healthy
   - mark idempotence (double-calling same transition is a no-op)
   - **callback failure isolation**: a `persist_callback` raising
     `ValueError` must NOT propagate to the `mark_crashed`/`mark_healthy`
     caller, since they run inside `MCPClientManager.call_tool` and a
     leak would break tool execution
   - **HTTP transport participation**: an HTTP-transport
     `MCPServerUnavailableError` flips the registry to crashed
     (mirrors stdio behaviour, mentor ruling Q5)
   - lock contention: two concurrent `mark_crashed` calls on the same
     server_name don't corrupt state
2. **Persistence + endpoint augmentation + frontend label** — ~50 LOC.
   Wires the registry's persistence callback to write `mcp_servers`
   rows; adds `live_status` to GET /mcp-servers response; renders
   `(crashed)` annotation in Settings → MCP Servers list. NO new
   endpoint, NO new column.

## Risks I am pre-binding myself against

- No subprocess.poll() polling — purely reactive.
- No state-machine refactor of consent / auto-restart logic.
- No new endpoint, no new schema column.
- No frontend test framework added (F4 backlog still applies).
- Persistence is fire-and-forget; tool execution path **never** blocks
  on health-DB writes.

## Next step after mentor APPROVE

Commit 1: `dialekt/mcp/health.py` module + wire-in + pytest. ≤170 LOC.
