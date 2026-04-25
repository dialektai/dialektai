# M2 Этап 2.5 — Phase 1.5 implementation plan: Consent Modal + WS consumer

**Scope:** wire `MCPClientManager` + `MCPRuntime` into the chat WS
session so destructive MCP tool calls actually surface a consent
prompt to the user, then build the React consent modal that
renders the prompt + sends the decision back over the WS.

**Related:**
- Product design — `docs/M2_MCP_UI_DESIGN.md` §4 (consent modal,
  mentor-approved)
- Backend bridge already shipped in commit `099700f` — emits
  `mcp_consent_request`, awaits `mcp_consent_response`, validates
  request_id + decision, handles timeout / cancellation
- MCP client architecture: `dialekt.mcp.runtime.MCPRuntime`,
  `dialekt.mcp.sync_bridge.create_sync_mcp`,
  `dialekt.llm._plugin_context.bind_mcp_runtime` —
  the OI-side primitives are already paved (see
  `python/dialekt/mcp/sync_bridge.py` docstring lines 24-50 for
  the canonical wiring pattern).

---

## 1. Two commits

This phase ships in two narrow, revertable commits:

- **1.5a backend** — `feat(backend): construct MCPRuntime per ws_chat
  session and bind into make_interpreter()`. Purely Python.
- **1.5b frontend** — `feat(frontend/chat): MCP consent modal and WS
  handler`. Purely React.

Each gets independent mentor commit review. Splitting reduces blast
radius — backend ships first; if frontend slips, the backend WS
bridge from `099700f` still works against a future modal without
re-merging.

---

## 2. Commit 1.5a — backend MCPRuntime in ws_chat

### 2.1 Files

- `python/server.py` — only.

### 2.2 Imports

Top-of-section comment + new imports near the existing MCP-bridge
helpers (introduced in commit `099700f`):

```py
from dialekt.mcp import (
    BearerAuth, EnvVarsAuth, NoAuth,
    HttpTransportSpec, StdioTransportSpec,
    MCPClient, MCPClientManager,
    provider_for_autonomy,
)
from dialekt.mcp.runtime import MCPRuntime
from dialekt.mcp.sync_bridge import create_sync_mcp
from dialekt.mcp.secrets_resolver import resolve_env, resolve_secret_refs
from dialekt.llm._plugin_context import bind_mcp_runtime, unbind_mcp_runtime
```

### 2.3 New helper: build per-session MCPRuntime

A pure function that, given the agent's parsed manifest + a session
WebSocket, returns either `(runtime, sync_adapter, manager)` or
`None` if the manifest has no `mcp_servers`.

```py
async def _build_session_mcp_runtime(
    *, manifest, ws, ws_id: str, loop, agent_id: str,
) -> Optional[Tuple[MCPRuntime, Any, MCPClientManager]]:
    servers = list(getattr(manifest, "mcp_servers", None) or [])
    if not servers:
        return None

    server_specs: dict[str, ServerSpec] = {}
    for entry in servers:
        if entry.transport == "stdio":
            env = resolve_env(dict(entry.env or {}), server_name=entry.name)
            transport = StdioTransportSpec(
                command=list(entry.command or []),
                env=env, cwd=entry.cwd,
                timeout_seconds=float(entry.timeout_seconds or 30.0),
            )
            creds = EnvVarsAuth(vars=env) if env else NoAuth()
        else:
            transport = HttpTransportSpec(
                url=entry.url,
                timeout_seconds=float(entry.timeout_seconds or 30.0),
            )
            if entry.auth and entry.auth.type == "bearer":
                token = resolve_secret_refs(entry.auth.token, server_name=entry.name)
                creds = BearerAuth(token=token)
            else:
                creds = NoAuth()
        server_specs[entry.name] = (transport, creds, float(entry.timeout_seconds or 30.0))

    autonomy = (manifest.autonomy.recommended if manifest.autonomy else "ask-before-write")
    prompt_fn = _build_consent_prompt_fn(ws, ws_id, loop)
    consent_provider = provider_for_autonomy(autonomy, prompt_fn)

    audit_cb = _make_audit_callback(agent_id)   # see 2.5
    manager = MCPClientManager(agent_id=agent_id, audit_callback=audit_cb)
    runtime = MCPRuntime(
        manager=manager,
        server_specs=server_specs,
        consent_provider=consent_provider,
        tool_metadata_fetcher=lambda name: _fetch_tools_via_manager(manager, name, server_specs),
        audit_callback=audit_cb,
        agent_id=agent_id,
        binding_id=None,
    )
    sync_adapter = create_sync_mcp(runtime)
    return runtime, sync_adapter, manager
```

### 2.4 Wire into `ws_chat` join handler

Right after `agent_for_join = await db_get_agent(sess_row[0])` and
the agent context resolution, when the parsed manifest has
`mcp_servers`:

```py
mcp_runtime = None
mcp_manager = None
mcp_bind_token = None
if agent_for_join and agent_ctx_for_join and agent_ctx_for_join.get("manifest"):
    parsed = agent_ctx_for_join["manifest"]
    built = await _build_session_mcp_runtime(
        manifest=parsed, ws=ws, ws_id=ws_id, loop=loop, agent_id=agent_for_join["id"],
    )
    if built is not None:
        mcp_runtime, sync_adapter, mcp_manager = built
        mcp_bind_token = bind_mcp_runtime(sync_adapter)
```

In the `finally:` block, alongside `_active_interpreters.pop(ws_id, None)`:

```py
if mcp_bind_token is not None:
    try:
        unbind_mcp_runtime(mcp_bind_token)
    except Exception:
        pass
if mcp_manager is not None:
    try:
        await mcp_manager.shutdown()
    except Exception:
        pass
```

### 2.5 Audit callback

`MCPClientManager.audit_callback` and `MCPRuntime.audit_callback`
both expect a callable that takes `kind, **fields` and writes to the
audit_log table. The simplest implementation reuses the existing
`/audit/log` POST endpoint via the PluginContext that's already set
up in startup. Sketch:

```py
def _make_audit_callback(agent_id: str):
    def _cb(kind: str, **fields):
        from dialekt.llm._plugin_context import get_context
        ctx = get_context()
        try:
            ctx.post("/audit/log", json={"agent_id": agent_id, "kind": kind, **fields})
        except Exception:
            log.debug("MCP audit write failed", exc_info=True)
    return _cb
```

Sync, in-memory; non-fatal on failure (audit is best-effort, not on
the critical path of the consent flow).

### 2.6 Tool metadata fetcher

`MCPRuntime` needs a way to fetch a server's tool list lazily. The
simplest impl reuses the manager:

```py
async def _fetch_tools_via_manager(manager, name, server_specs):
    transport, creds, _ = server_specs[name]
    client = await manager.get_client(name, transport, creds)
    result = await client.list_tools()
    return list(result.tools)
```

Defined as a closure inside `_build_session_mcp_runtime` to capture
the manager and specs without leaking globals.

### 2.7 Tests

New file `python/tests/test_ws_chat_mcp_integration.py` (≈ 4 cases,
each TestClient-based):

1. **session-with-mcp builds runtime and binds it** — join a session
   whose agent manifest has one stdio mcp_server (filesystem MCP via
   the same fixture used in `test_mcp_e2e_filesystem.py`); assert
   `_active_interpreters[ws_id]` exists AND that the runtime was
   bound (probe via a side-effect log line or by exposing
   `_active_mcp_runtimes: dict[str, MCPRuntime]` for test inspection).
2. **session-without-mcp leaves bind unchanged** — agent without
   mcp_servers; assert no bind/unbind calls happened.
3. **disconnect cleans up the manager** — connect, disconnect, assert
   `manager.shutdown()` ran (mock the manager and check call).
4. **manifest secret resolution failure surfaces** — mcp_servers
   entry references `${secrets.missing}`; assert ws_chat does NOT
   crash on join, surfaces an error frame to the WS client, and the
   chat continues without MCP. (Soft-fail: an MCP setup error should
   not kill the chat.)

Test #1 needs careful fixture work — the existing
`test_mcp_e2e_filesystem.py` already spawns a real filesystem MCP
in a temp dir; reuse that pattern.

### 2.8 Line budget

Estimate: backend changes ≈ 100-150 lines net (helpers + wiring +
tests). If `_build_session_mcp_runtime` exceeds 80 lines, extract to
`python/dialekt/mcp/session_helpers.py` per dias-style cleanliness;
flag and ask first.

---

## 3. Commit 1.5b — frontend ConsentModal + WS handler

### 3.1 Files

- `frontend/src/components/ConsentModal.jsx` — new component
  (~150 lines including styles).
- `frontend/src/hooks/useChat.js` (or wherever the chat WS is held —
  verify during implementation) — add `mcp_consent_request` listener
  + `sendConsentResponse(request_id, decision)` API.
- `frontend/src/screens/MainScreen.jsx` — render `<ConsentModal>`
  driven by hook state.

### 3.2 Component shape

```jsx
<ConsentModal
  request={{                          // null = no request, hide modal
    request_id: "abc-…",
    server_name: "github",
    tool_name: "create_issue",
    arguments: { ... },
    destructive: true,
    destructive_source: "explicit",
  }}
  onApprove={() => sendConsentResponse(req.request_id, "approved")}
  onApproveSession={() => sendConsentResponse(req.request_id, "approved_session")}
  onDeny={() => sendConsentResponse(req.request_id, "denied")}
/>
```

Layout per design doc §4.1:
- Centered overlay + scrim `rgba(0,0,0,0.6)`. Always centered, shrink
  to `calc(100vw - 32px)` on narrow windows (mentor ruling 5).
- Header: `🔐 Permission required`.
- Two columns of meta: server / tool (with destructive badge if
  applicable).
- Arguments block — pre-formatted JSON inside a code-styled box.
- Three buttons: `Deny (Esc)`, `Approve once (Enter)`, `Approve for
  this session (Shift+Enter)`.

### 3.3 Keyboard handling

`useEffect` that attaches a `keydown` listener while the modal is
open, removes on unmount/close. Maps Enter → onApprove, Shift+Enter
→ onApproveSession, Esc → onDeny. Tab/Shift+Tab cycles buttons
(reuses native focus order — no manual trap, just `autoFocus` on
the safer "Approve once" button per design §4.3).

### 3.4 Queuing multiple pending requests

If the agent fires N tools in parallel and the backend prompts for
each, the modal shows them one at a time. State shape: `pendingQueue:
ConsentRequest[]`. Modal renders the head; resolving it shifts the
queue. Header copy: `Request 1 of 3` when `queue.length > 1`.

### 3.5 Timeout handling

If backend emits `mcp_consent_timeout` for the active request_id,
the modal swaps the buttons for an `OK` button + amber error banner
("Permission request timed out. Try sending the message again."). On
OK, the request is removed from the queue (already DENIED on the
backend per `_consent_prompt_fn`'s timeout branch).

### 3.6 Styles

Match SettingsScreen tokens (`T.bg2`, `T.border`, `T.cyan`, etc.).
No new design tokens. Scrim z-index 9999 to clear the right panel.

### 3.7 Tests

Project baseline is zero frontend tests. Continue baseline (mentor
ruling on Phase 1.3 still applies). Verification surface:

1. Backend tests in 1.5a cover the WS protocol shape.
2. Phase 2.1 GitHub MCP E2E exercises modal end-to-end.
3. Visual smoke in Tauri dev build before declaring 1.5b done.

### 3.8 Line budget

Component ≈ 150 lines, hook delta ≈ 30 lines, MainScreen render
delta ≈ 5 lines. ~200 line ceiling for 1.5b. If hook integration
spreads across more than 2 files, pause.

---

## 4. Open questions for mentor

1. **Audit callback shape — POST to /audit/log via PluginContext, or
   write to db directly inside the callback?** Sketch above uses the
   HTTP path (simpler, matches existing pattern in retry_loop). Direct
   DB write is faster but adds threading concerns from the OI worker.
   My lean: HTTP via PluginContext.

2. **Soft-fail on MCP setup errors at join.** If a mcp_servers entry
   references a missing secret OR a transport spec construction
   fails, the chat still works — just without MCP. Send a
   `{type: "mcp_setup_error", error, server_name}` frame so the
   frontend can render a row-banner; do NOT kill the WS or 500.
   Confirm.

3. **`_active_mcp_runtimes` exposure for testing** — module-global
   dict keyed by ws_id. Useful for test #1 above. Acceptable, or use
   a different probe (audit log row, log line)?

4. **Where the chat WS lives in the frontend.** `useChat` is the
   likely owner; will verify during implementation. If the WS is
   inlined into MainScreen instead, we adjust the hook API
   accordingly. Mentor ok with discovery during impl rather than
   pre-locking?

5. **Secrets-in-arguments concern (design doc §6 INFO note).** Tool
   arguments are forwarded untouched into the WS frame for the user
   to inspect — this is by design (consent modal must show what will
   be called). No redaction in v0.20.0. Confirm still ok.

---

## 5. Known deferrals

- `Approve all pending` button during multi-tool bursts — design §10,
  deferred. Modal queues one-by-one in v0.20.0.
- Tool argument redaction — §6 INFO, deferred until MCP argument
  schemas land.
- Per-tool allow/deny scoping in the runtime — already deferred at
  manifest level (Phase 1.3); re-confirmed here.

---

## 6. Change log

- `2026-04-25 v1` — initial plan (Claude Code, pending mentor review).
