# Using MCP in a dialekt agent

**Audience:** agent authors — the humans writing manifests and the
Python blocks those manifests wire up. Contributors to the
`dialekt.mcp` package itself should read `M2_MCP_DESIGN.md` first.

**Status:** v0.20.0. Assumes spec `1.1.0` manifests and the
validator at v0.3.0 or newer.

---

## Mental model in one paragraph

An agent manifest lists the external MCP servers the agent is
allowed to talk to. At chat time, dialekt opens those servers
lazily (first tool call), dialekt's `MCPClientManager` tracks them
for the life of the session, and the agent's Python block reaches
them through the `ctx.mcp` attribute chain. Destructive tools
prompt for consent unless the manifest says otherwise. Every call
writes an audit row.

## Declaring MCP servers in the manifest

Spec `1.1.0` adds a top-level `mcp_servers` list:

```yaml
spec_version: "1.1.0"
minimum_dialekt_version: "0.20.0"

# ... metadata, model, system_prompt as usual ...

capabilities:
  groups:
    - filesystem_read      # existing capabilities as before
    - mcp_tools            # NEW — required when mcp_servers is non-empty
  exceptions: []

mcp_servers:
  - name: "github"
    description: "GitHub repo ops"
    transport: "stdio"
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${secrets.github_token}"
    timeout_seconds: 30

  - name: "internal-jira"
    description: "Internal Jira over HTTPS"
    transport: "http"
    url: "https://jira.company.internal/mcp"
    auth:
      type: "bearer"
      token: "${secrets.jira_token}"
    timeout_seconds: 20

secrets_required:
  - name: "github_token"
    description: "GitHub personal access token with repo scope"
  - name: "jira_token"
    description: "Jira bearer token"
```

Each entry:
- `name` is an agent-local identifier (lowercase, `[a-z0-9_-]+`).
  Used in tool calls as `ctx.mcp.<name>.<tool>(...)`.
- `transport` is `"stdio"` or `"http"`.
- For `stdio`, `command` is an argv list and optional `env` is
  merged into the subprocess environment.
- For `http`, `url` points at the Streamable HTTP endpoint and
  optional `auth` carries a bearer token.
- `timeout_seconds` bounds per-tool-call latency (default 30s).
- `allow_tools` / `deny_tools` restrict which advertised tools the
  agent may invoke. Default: all tools allowed.

### Secret references

Any `${secrets.name}` placeholder in `env` values or `auth.token`
is resolved from the dialekt keyring at load time. Place-named
under service `"dialekt"`, account `"mcp.<server_name>.<name>"`.
The validator auto-adds any references to `secrets_required` with
a warning if they weren't declared explicitly — declaring them
yourself gives the dialekt onboarding UX a human-readable prompt.

### The `mcp_tools` capability

When `mcp_servers` is non-empty the manifest MUST declare
`mcp_tools` in `capabilities.groups`. The host refuses to load
manifests that use MCP without asking for the capability — a
single switch pilots can flip to block agents that try to smuggle
in MCP access.

## Calling tools from an agent's Python block

Inside an OI code block the agent writes sync Python:

```python
result = ctx.mcp.github.create_issue(
    repo="dialektai/dialektai",
    title="Investigate flaky test",
    body="We saw this fail twice on macOS runners — see #42.",
)
if result.isError:
    # Server-level tool error — inspect result.content for the reason.
    print("GitHub said no:", result.content[0].text)
else:
    print("Opened issue:", result.content[0].text)
```

Things the agent author should know:

1. **Return value** is the SDK's `CallToolResult`. Check
   `result.isError` first; structured content is in
   `result.content` (a list of `TextContent` / `ImageContent` /
   etc., the first element is usually what you want).
2. **Consent prompts are silent when unnecessary.** If the agent's
   `autonomy` is `autonomous`, or the tool is non-destructive,
   the call dispatches immediately. Otherwise dialekt shows a
   consent dialog and waits for the user's decision.
3. **Denial raises, not returns.** A user clicking "Deny" surfaces
   as a `dialekt.mcp.MCPConsentDenied` exception, which the agent
   code can catch and recover from:
   ```python
   from dialekt.mcp import MCPConsentDenied
   try:
       result = ctx.mcp.github.create_issue(...)
   except MCPConsentDenied:
       print("User declined — retrying with a less destructive plan.")
       ...
   ```
4. **Errors are classified.** Transport-level failures show up as
   `MCPServerUnavailableError`; a call that overran its
   `timeout_seconds` is `MCPTimeoutError`; a tool the server
   doesn't advertise is `MCPToolNotFoundError`. See
   `M2_MCP_DESIGN.md` Decision 6 for the full taxonomy.
5. **Arguments are keyword-only.** Positional args aren't supported
   — the attribute chain doesn't know a tool's parameter order, so
   everything goes through kwargs.

## How `ctx.mcp` gets wired up

This part is internal but worth understanding because it drives
the rules above.

`PluginContext.mcp` is a property that reads a `ContextVar`
binding set by the WebSocket chat handler at turn start:

```
       ws_chat turn start
              │
              ▼
    ctx.new_mcp_manager(agent_id)   → MCPClientManager
              │
              ▼
    MCPRuntime(manager, server_specs, consent_provider, ...)
              │
              ▼
    create_sync_mcp(runtime)        → SyncRuntimeAdapter
              │
              ▼
    bind_mcp_runtime(adapter)       → ContextVar set
              │
              ▼
    await asyncio.to_thread(run_oi_block)
              │            │
              │            ▼
              │     ctx.mcp.github.create_issue(...)  (sync, in worker thread)
              │            │
              │            ▼
              │     SyncMCPNamespace → asyncio.run_coroutine_threadsafe(
              │                           runtime.invoke_tool(...), main_loop)
              │            │
              ▼            ▼
        main loop runs invoke_tool:
          1. list_tools → cached metadata
          2. destructive? autonomy? → maybe prompt consent
          3. manager.call_tool → audit + dispatch
          4. return CallToolResult
              │
              ▼
    sync caller unwraps the future, returns to OI
              │
              ▼
       ws_chat turn end
              │
              ▼
    await adapter.shutdown()        → closes all MCPClients
```

Two important properties of this wiring:

- The MCP subprocesses / HTTP clients live on the **main asyncio
  loop**. The sync shim never migrates them. This avoids the
  cross-loop issue that bit asyncpg pools in the DialektSQL
  plugin (see `PLUGIN_ARCHITECTURE.md`).
- `ContextVar` propagates through `asyncio.to_thread`, so the
  ContextVar binding set in the handler is visible inside the
  worker thread. No thread-local hacks needed.

## Autonomy × destructive tool matrix

For reference — the runtime layer enforces this automatically:

| `autonomy`         | Destructive tool     | Non-destructive tool |
|--------------------|----------------------|----------------------|
| `autonomous`       | no prompt            | no prompt            |
| `ask-before-write` | prompt (session-cached) | no prompt         |
| `review-only`      | auto-deny (audited)  | no prompt            |
| `manual`           | prompt (session-cached) | prompt (session-cached) |
| `sandbox-only`     | prompt (like ask-before-write in v0.20.0) | no prompt |

**Destructive** is determined first by MCP tool annotations
(`destructive` / `writeable`), falling back to a name-pattern
heuristic (`create`, `delete`, `update`, `send`, `write`, …).
False positives (asking unnecessarily) are acceptable; false
negatives (silently running a destructive tool) are not.

## Operational notes

Pointers to surrounding docs:

- Audit rows land in the `audit_log` SQLite table. See
  `MCP_OPERATIONS.md` for the column layout and known gaps.
- Rate limit is 60 tool calls per minute per agent session
  across all connected servers. Breach raises
  `MCPRateLimitError`; see `MCP_OPERATIONS.md`.
- Manager + runtime lifecycle is owned by the ws_chat handler
  — the context does not cache managers across sessions. Details
  in `M2_MCP_DESIGN.md` Decision 4.

## Quick troubleshooting

| Symptom | Likely cause |
|---|---|
| `MCPConfigError: server X not configured` | The server name in `ctx.mcp.X.tool(...)` doesn't match any `mcp_servers[].name` in the manifest. |
| `MCPServerUnavailableError` on first call | The command in the manifest isn't on PATH, OR the HTTP URL isn't reachable. Check the error message for which. |
| `MCPTimeoutError: handshake` | The MCP server accepted stdin/TCP but never answered `initialize`. Either it's broken or the wrong command was spawned. |
| `MCPTimeoutError: <tool> timed out` | The per-call `timeout_seconds` is too tight for this tool. Bump it in the manifest. |
| `MCPConsentDenied` | User clicked "Deny" on the consent prompt — legitimate, treat it as a recoverable decline. |
| `MCPRateLimitError` | Agent fired too many tools in a 60-second window. Either slow down or raise the limit (manager kwarg). |
| Agent code raises `RuntimeError: No MCP runtime bound` | You're running agent code outside a ws_chat session. MCP only works when the session handler has bound a runtime. |
