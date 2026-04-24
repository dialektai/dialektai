# Connecting Claude Desktop to dialekt

**Audience:** pilots who want to use Claude Desktop (or Cursor, or
any other MCP host) with their local dialekt — querying their DB,
listing their agents, reading files from opted-in directories.

**Status:** v0.20.0 (Этап 2 complete).

Companion docs:
- [MCP_CLIENT_USAGE.md](MCP_CLIENT_USAGE.md) — the *other* direction
  (agents inside dialekt talking out to external MCP servers).
- [M2_MCP_SERVER_DESIGN.md](M2_MCP_SERVER_DESIGN.md) — architectural
  decisions behind this surface.
- [MCP_OPERATIONS.md](MCP_OPERATIONS.md) — audit log schema and
  operational SQL snippets.

---

## One-paragraph mental model

Claude Desktop (or another MCP host) spawns `dialekt-mcp` as a
stdio subprocess. That subprocess authenticates with an API key
from your dialekt config, opens a long-lived HTTP connection back
to your running dialekt desktop app, and exposes nine tools
(5 database + 2 file + 2 agent) to Claude. Claude uses those
tools in your chat the same way it uses any other MCP server.

Your data stays local. `dialekt-mcp` is a pure protocol adapter —
nothing leaves your machine except what you tell Claude to send
upstream through its own chat.

---

## Prerequisites

1. The dialekt desktop app is installed and **running**.
2. You have Claude Desktop installed. Other MCP hosts work the
   same way; these instructions use Claude Desktop as the example.
3. (For manual/dev installs) Python 3.10+ and the `dialekt-mcp`
   binary or script on your `PATH`. Packaged installs handle this
   automatically via the installer.

---

## Setup in three steps

### 1. Copy an API key + config snippet from dialekt

1. Open dialekt → **Settings** → **Integrations**.
2. Find the **MCP Server** panel. Click **Copy Claude Desktop snippet**.
3. The snippet will look like this (yours will have a real key):

   ```json
   {
     "mcpServers": {
       "dialekt": {
         "command": "dialekt-mcp",
         "args": ["--api-key", "dsk_live_xxxxxxxxxxxx"]
       }
     }
   }
   ```

   Or the env-based variant (same effect — use whichever you prefer):

   ```json
   {
     "mcpServers": {
       "dialekt": {
         "command": "dialekt-mcp",
         "env": {
           "DIALEKT_MCP_API_KEY": "dsk_live_xxxxxxxxxxxx"
         }
       }
     }
   }
   ```

### 2. Paste into Claude Desktop's config

The Claude Desktop config file lives at:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Merge the `mcpServers` entry from the snippet into that file. If
the file doesn't exist, create it with exactly the snippet's content.

### 3. Restart Claude Desktop

Fully quit and relaunch. Claude Desktop will spawn `dialekt-mcp` on
startup and discover its tools. You'll see `dialekt` appear in the
MCP-servers list in Claude's UI — expand it to see the nine tools.

---

## Verifying the connection

In a new Claude chat, ask:

> Using dialekt, list the database connections I have configured.

Claude calls `dialekt_list_connections`. You should see your
connections listed (names and types only — no passwords, ever).

If it doesn't work, read the next section.

---

## Troubleshooting

### "dialekt-mcp: cannot reach dialekt backend at ..."

The desktop app isn't running, or it's running on a non-default
port. Open the app and try again. If it's on a non-default port,
add `--backend http://127.0.0.1:<port>` to the `args` or set
`DIALEKT_BACKEND_URL` in the `env` block.

### "dialekt-mcp: API key not recognised"

The key in your Claude Desktop config doesn't match any entry in
`~/.dialekt/mcp-server.toml`. Re-copy from dialekt → Settings →
Integrations and re-paste. If you recently rotated the key, the
old one was deleted; copy the new one.

### "dialekt-mcp: no API key supplied"

Claude Desktop is spawning the binary but you haven't configured a
key. See Step 1.

### Commands like `dialekt_query_database` return HTTP 400

The dialekt backend's SQL safety parser rejects mutations by
design. SELECT-only queries work; UPDATE / DELETE / CREATE do not.
If you need to mutate, go through the dialekt UI directly.

### Tools show up but return "not enabled for the active API key"

Your key has a per-key `enabled_tools` allow-list in the config
that doesn't include the tool you're calling. Edit
`~/.dialekt/mcp-server.toml` and either expand the allow-list or
remove it entirely to allow all tools in the enabled categories.

### File tools (`dialekt_read_file`, `dialekt_list_directory`) refuse every path

`allowed_file_roots` is empty in your config (the default). This
is secure-by-default — file access must be explicitly granted.
Edit `~/.dialekt/mcp-server.toml`:

```toml
[server]
allowed_file_roots = [
    "~/Documents/my-project",
    "/shared/reports",
]
```

Save, restart Claude Desktop. The tool can now read/list inside
those directories but NOT outside (symlinks are resolved before
the check, so shenanigans won't work).

### I want to see what Claude is actually calling

In dialekt → Settings → Integrations → **Recent MCP activity**,
or query the audit table directly:

```sql
SELECT ts, action, result, duration_ms
FROM audit_log
WHERE kind = 'mcp_server_tool_call'
ORDER BY ts DESC
LIMIT 20;
```

Every tool call appears here — who (API key id in `target`), what
tool (`action`), when, how fast, what result.

---

## Advanced configuration

### Per-key tool scoping

You can limit what a specific API key can do. Useful if you have
multiple MCP hosts connected and want a tight-perimeter key for
one of them:

```toml
[server]
api_keys = [
    # Cursor can do DB stuff but not file reads
    {
        id = "cursor",
        value = "cursor-key-sufficiently-long",
        enabled_tools = [
            "dialekt_list_connections",
            "dialekt_query_database",
            "dialekt_list_tables",
            "dialekt_describe_table",
        ],
    },
    # Claude Desktop gets everything
    { id = "claude-desktop", value = "claude-desktop-key-sufficiently-long" },
]
```

### Rate limit tuning

The default is 120 tool calls per minute per key. If you're
hammering the connection for an automated workflow:

```toml
[server]
rate_limit_per_minute = 300
```

Raising this too high means a runaway agent can consume your
backend's attention. 300 is a reasonable ceiling for batch work;
120 is fine for interactive chat.

### Multiple hosts, one dialekt

Each MCP host (Claude Desktop, Cursor, …) spawns its own
`dialekt-mcp` subprocess. They are independent — separate auth,
separate rate-limit windows, separate audit rows. Just give each
its own API key (or they can share one; the `id` column in the
audit table tells them apart regardless).

---

## Environment variables

When Claude Desktop's config uses `env` instead of `args` (the
second snippet variant in Step 1), these variables are honored:

| Variable                  | Purpose                                        |
|---------------------------|------------------------------------------------|
| `DIALEKT_MCP_API_KEY`     | Authentication (alternative to `--api-key`)    |
| `DIALEKT_BACKEND_URL`     | dialekt backend URL, default `http://127.0.0.1:8765` |
| `DIALEKT_MCP_CONFIG_PATH` | Override config file location                  |
| `DIALEKT_MCP_LOG_LEVEL`   | `DEBUG` / `INFO` / `WARNING` / `ERROR`         |

`DIALEKT_MCP_LOG_LEVEL=DEBUG` is the most useful one when
debugging — the log lines go to Claude Desktop's own MCP-server
log (the host aggregates stderr from each subprocess).

---

## What this does NOT do in v0.20.0

- **Streamable HTTP transport** — remote Claude Desktop over
  Tailscale / Cloudflare would need this. Deferred to v0.25.0
  with the TLS + OAuth story.
- **`dialekt_invoke_agent`** — the tool that would let Claude
  Desktop run a whole dialekt agent as a tool. Deliberately
  omitted rather than shipped as a stub. Lands in M3 when the
  session + streaming + consent propagation work is real.
- **Writing to DBs / creating agents / modifying settings** —
  the server is read-biased by design. Destructive actions stay
  in the dialekt desktop UI.
- **Credentials leaving the machine** — connection passwords and
  API keys live in dialekt's keyring; they are scrubbed from
  every response before it crosses the MCP wire.

## Related

- [`MCP_CLIENT_USAGE.md`](MCP_CLIENT_USAGE.md) — agents inside
  dialekt consuming external MCP servers (the other direction).
- [`M2_MCP_SERVER_DESIGN.md`](M2_MCP_SERVER_DESIGN.md) — seven
  design decisions + open-question rulings that shaped this.
- [`MCP_OPERATIONS.md`](MCP_OPERATIONS.md) — audit schema details
  + SQL recipes for common operational questions.
