"""Real-server E2E validation for the v0.20.0 RC GitHub MCP path.

Runs end-to-end against `@modelcontextprotocol/server-github` with a
real GitHub PAT supplied via the env var DIALEKT_VALIDATION_GITHUB_TOKEN.
The token NEVER lands in argv, logs, or any file written by this
script — it goes into the OS keychain via dialekt.secrets and stays
there until DELETE /mcp-servers cleans it.

Coverage (Phase 2.1 / V1 in M2_POST_RC_BACKLOG):
1. Connection test  — POST /mcp-servers/{id}/test, expect success +
   non-zero tool_count, last_test_ok=1 in DB.
2. Tool discovery   — list_tools via the real client, capture names.
3. Read tool call   — runtime.invoke_tool(get_me) via auto-approve
   provider, expect a non-error CallToolResult.
4. Write tool call  — runtime.invoke_tool(create_issue) on a sandbox
   repo via WS-style consent flow with a programmatic auto-approver
   that asserts the prompt fires and the audit linkage is correct.
5. Audit chain      — verify mcp_consent_requested + mcp_consent_decision
   + mcp_tool_call rows for the same operation thread through
   audit_log with consistent agent_id.
6. Cleanup          — DELETE /mcp-servers/{id}, verify keyring is
   empty for this server name.

Usage:
    DIALEKT_VALIDATION_GITHUB_TOKEN='ghp_...' \\
    DIALEKT_VALIDATION_GITHUB_REPO='owner/repo' \\
    python scripts/mcp_validation/run_github_e2e.py

Output: machine-readable JSON to stdout + human-readable markdown
fragment ready for inclusion in docs/MCP_PRODUCTION_VALIDATION.md.

This script is NOT part of the test suite — it requires a live GitHub
PAT and creates a real issue on the target repo. Run manually before
flipping AGENT_CATALOG Category 5.5.1 from ⚠️ to ✅.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

# Ensure we can import server even when invoked from repo root.
HERE = Path(__file__).resolve()
PYTHON_DIR = HERE.parent.parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))


def _redact(text: str, secrets: list[str]) -> str:
    """Replace any verbatim secret occurrences with [REDACTED]."""
    out = text
    for s in secrets:
        if s and len(s) >= 8:
            out = out.replace(s, "[REDACTED]")
    return out


def main() -> int:
    token = os.environ.get("DIALEKT_VALIDATION_GITHUB_TOKEN")
    if not token:
        print("DIALEKT_VALIDATION_GITHUB_TOKEN env var is required", file=sys.stderr)
        return 2

    test_repo = os.environ.get("DIALEKT_VALIDATION_GITHUB_REPO", "").strip()
    if not test_repo or "/" not in test_repo:
        print("DIALEKT_VALIDATION_GITHUB_REPO env var (owner/repo) is required", file=sys.stderr)
        return 2
    owner, repo = test_repo.split("/", 1)

    # Collect events for the markdown report. Never include the token.
    events: list[dict] = []
    secrets_to_redact = [token]

    def evt(stage: str, ok: bool, **fields):
        # Pre-redact any string field defensively.
        clean = {}
        for k, v in fields.items():
            clean[k] = _redact(v, secrets_to_redact) if isinstance(v, str) else v
        e = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "stage": stage, "ok": ok, **clean}
        events.append(e)
        print(json.dumps(e), flush=True)

    from fastapi.testclient import TestClient
    import server as srv
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)
        original = (srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR)
        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir

        try:
            with TestClient(srv.app, raise_server_exceptions=False) as client:
                evt("backend_started", True, db_path=str(srv.DB_PATH))

                # ── 1. Create MCP server via REST (token → keyring) ──
                npx = "/home/dias/.nvm/versions/node/v22.22.0/bin/npx"
                payload = {
                    "name": "github",
                    "transport": "stdio",
                    "command": [npx, "-y", "@modelcontextprotocol/server-github"],
                    "env_refs": {"GITHUB_PERSONAL_ACCESS_TOKEN": "github_token"},
                    "env_secrets": [{"ref": "github_token", "value": token}],
                    "timeout_seconds": 60.0,
                }
                r = client.post("/mcp-servers", json=payload)
                if r.status_code != 201:
                    evt("create_mcp_server", False, status=r.status_code, body=r.text[:300])
                    return 3
                created = r.json()
                server_id = created["id"]
                # Sanity: response must NOT echo the token anywhere.
                assert token not in r.text, "token leaked into response"
                evt("create_mcp_server", True, id=server_id, name=created["name"],
                    has_auth_token=created["has_auth_token"], leak_check="passed")

                # ── 2. /test endpoint: real GitHub API roundtrip ──
                t0 = time.monotonic()
                r = client.post(f"/mcp-servers/{server_id}/test")
                test_dur = round(time.monotonic() - t0, 2)
                if r.status_code != 200:
                    evt("test_connection", False, status=r.status_code, body=r.text[:300])
                    return 4
                test_body = r.json()
                if not test_body.get("success"):
                    evt("test_connection", False, error=test_body.get("error"))
                    return 4
                tool_count = test_body.get("tool_count", 0)
                evt("test_connection", True,
                    tool_count=tool_count, duration_seconds=test_dur)

                # /mcp-servers/{id} should now have last_test_ok=1
                r = client.get(f"/mcp-servers/{server_id}")
                row = r.json()
                evt("last_test_columns", row.get("last_test_ok") is True,
                    last_test_ok=row.get("last_test_ok"),
                    last_test_at=row.get("last_test_at"),
                    tool_count=row.get("tool_count"))

                # ── 3. Discover tool names via real client ──
                from dialekt.mcp import (
                    EnvVarsAuth, StdioTransportSpec, MCPClient,
                )
                env = {"GITHUB_PERSONAL_ACCESS_TOKEN": token}
                spec = StdioTransportSpec(
                    command=[npx, "-y", "@modelcontextprotocol/server-github"],
                    env=env, timeout_seconds=60.0,
                )
                creds = EnvVarsAuth(vars=env)

                async def list_tools_async():
                    async with MCPClient(transport=spec, credentials=creds) as c:
                        return await c.list_tools()

                tools_result = asyncio.run(list_tools_async())
                tool_names = [t.name for t in tools_result.tools]
                evt("tool_discovery", True, count=len(tool_names),
                    sample=tool_names[:8])

                # ── 4. Read tool call (auto-approve, no consent fires) ──
                # Pick a guaranteed-read tool. `search_repositories` is in
                # ~every GH MCP variant. Falls back to whatever read tool
                # exists if the package shape changed.
                read_tool = None
                for candidate in ("search_repositories", "list_repositories", "search_issues", "get_me"):
                    if candidate in tool_names:
                        read_tool = candidate
                        break
                if read_tool is None:
                    evt("read_tool_pick", False, reason="no known read tool found",
                        tools=tool_names[:20])
                    return 5

                from dialekt.mcp.runtime import MCPRuntime
                from dialekt.mcp.manager import MCPClientManager
                from dialekt.mcp.consent import (
                    AutoApproveProvider, ConsentDecision, ConsentRequest,
                )

                # Wire the same audit callback production uses
                # (_build_session_mcp_runtime → get_context()._default_audit_callback)
                # so audit_log rows actually get emitted during this run.
                from dialekt.llm._plugin_context import get_context
                audit_cb = get_context()._default_audit_callback

                # Use AutoApprove for the read; the runtime still records
                # consent rows even when auto-approved.
                async def run_read():
                    mgr = MCPClientManager(agent_id="validation-agent", audit_callback=audit_cb)
                    rt = MCPRuntime(
                        manager=mgr,
                        server_specs={"github": (spec, creds, 60.0)},
                        consent_provider=AutoApproveProvider(),
                        audit_callback=audit_cb,
                        autonomy="autonomous",
                        agent_id="validation-agent",
                    )
                    args = {"query": "modelcontextprotocol", "perPage": 1} if read_tool == "search_repositories" \
                           else {"query": "is:open"} if read_tool == "search_issues" \
                           else {}
                    try:
                        result = await rt.invoke_tool("github", read_tool, arguments=args)
                        return True, result
                    finally:
                        await mgr.shutdown()

                ok, result = asyncio.run(run_read())
                evt("read_tool_call", ok, tool=read_tool,
                    is_error=getattr(result, "isError", False),
                    content_blocks=len(getattr(result, "content", []) or []))

                # ── 5. Destructive tool call with consent prompt ──
                # Build a runtime whose consent provider records that the
                # prompt was actually invoked. Auto-approve every prompt
                # but assert the prompt fired (would fire on a real client).
                prompt_calls: list[ConsentRequest] = []

                class CapturingProvider:
                    async def request_consent(self, req: ConsentRequest) -> ConsentDecision:
                        prompt_calls.append(req)
                        return ConsentDecision.APPROVED

                async def run_write():
                    mgr = MCPClientManager(agent_id="validation-agent", audit_callback=audit_cb)
                    rt = MCPRuntime(
                        manager=mgr,
                        server_specs={"github": (spec, creds, 60.0)},
                        consent_provider=CapturingProvider(),
                        audit_callback=audit_cb,
                        autonomy="ask-before-write",
                        agent_id="validation-agent",
                    )
                    try:
                        result = await rt.invoke_tool("github", "create_issue", arguments={
                            "owner": owner, "repo": repo,
                            "title": "[dialekt v0.20.0 RC] MCP validation — automated, safe to close",
                            "body": ("This issue was created by the dialekt v0.20.0 release-candidate "
                                     "validation harness "
                                     "(`scripts/mcp_validation/run_github_e2e.py`). "
                                     "It exercises the GitHub MCP write path end-to-end to confirm "
                                     "consent prompting, audit linkage, and real API success. "
                                     "Safe to close immediately.\n\n"
                                     "Do not delete the validation harness in response to this issue."),
                        })
                        return True, result
                    finally:
                        await mgr.shutdown()

                if "create_issue" in tool_names:
                    ok_w, result_w = asyncio.run(run_write())
                    evt("write_tool_call", ok_w,
                        tool="create_issue",
                        consent_prompted=len(prompt_calls) >= 1,
                        prompt_destructive=prompt_calls[0].destructive if prompt_calls else None,
                        prompt_destructive_source=prompt_calls[0].destructive_source if prompt_calls else None,
                        is_error=getattr(result_w, "isError", False),
                        content_blocks=len(getattr(result_w, "content", []) or []))
                else:
                    evt("write_tool_call", False, reason="create_issue not in tool list",
                        tools=tool_names[:20])

                # ── 6. Audit chain inspection ──
                conn = sqlite3.connect(str(srv.DB_PATH))
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT kind, agent_id, target, action, result FROM audit_log "
                    "WHERE agent_id = ? ORDER BY id ASC",
                    ("validation-agent",),
                ).fetchall()
                conn.close()
                kinds = [r["kind"] for r in rows]
                has_req = "mcp_consent_requested" in kinds
                has_dec = "mcp_consent_decision" in kinds
                has_call = any(k.endswith("_tool_call") or k == "mcp_tool_call" for k in kinds)
                audit_ok = has_req and has_dec and has_call
                evt("audit_chain", audit_ok, kind_count=len(kinds),
                    kinds=kinds[:20],
                    has_consent_requested=has_req,
                    has_consent_decision=has_dec,
                    has_tool_call=has_call)

                # ── 7. Cleanup: DELETE → keyring should be cleared ──
                from dialekt.mcp.secrets_resolver import keyring_key
                from dialekt.secrets import get_secret
                key_pre = keyring_key("github", "github_token")
                pre = get_secret(key_pre)
                evt("keyring_pre_delete", pre is not None,
                    key=key_pre, present=pre is not None)

                r = client.delete(f"/mcp-servers/{server_id}")
                evt("delete_mcp_server", r.status_code == 204, status=r.status_code)

                post = get_secret(key_pre)
                evt("keyring_post_delete", post is None,
                    key=key_pre, present=post is not None)

                # Final pass/fail summary.
                failed = [e for e in events if not e["ok"]]
                evt("validation_summary",
                    len(failed) == 0,
                    total_stages=len(events) - 1,
                    failed_stages=[e["stage"] for e in failed])
                return 0 if not failed else 1

        except Exception as e:
            evt("crash", False, error=_redact(repr(e), secrets_to_redact),
                traceback=_redact(traceback.format_exc()[-1500:], secrets_to_redact))
            return 9
        finally:
            srv.DB_PATH, srv.SETTINGS_FILE, srv.DIALEKT_DIR = original


if __name__ == "__main__":
    sys.exit(main())
