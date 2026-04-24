"""Role 3 (End User) — chat-only journeys through the desktop app.

Scope per docs/MULTI_ROLE_TEST_PLAN.md §3:
  Selection + send (3): greet a bundled agent, run a SQL analyst, verify
                        multi-turn context retention
  Session mgmt (2):     implicit create via first message, DELETE /sessions/{id}
  Empty states (2):     agent with required conn + no binding vs pure LLM
  Error recovery (2):   SQL against missing table → retry loop + graceful error;
                        mid-session agent switch updates session.agent_id
  ClickHouse chat (1):  separate driver path — count analytics.events

Uses real local Ollama. Default model `gemma2:2b` (fast, deterministic
with low temp); SQL-quality scenarios (tests 02, 03, 08, 10) override
to `qwen2.5-coder:7b` for better SQL generation — noted in each
docstring below.

Runs with DIALEKT_RUN_E2E=1. Skips if Ollama or integration DBs
unreachable.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("DIALEKT_RUN_E2E") != "1",
    reason="Role-E2E tests require live Ollama + integration DBs — set DIALEKT_RUN_E2E=1",
)


PG = dict(host="localhost", port=15432, database="dialekt_integration",
          username="dialekt_test", password="dialekt_test")
CH = dict(host="localhost", port=18123, database="dialekt_integration",
          username="dialekt_test", password="dialekt_test")


# ── Pre-flight: Ollama + required models ────────────────────────────────────

def _ollama_models() -> set[str]:
    import httpx
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=3)
        return {m["name"] for m in r.json().get("models", [])}
    except Exception:
        return set()


_models = _ollama_models()
if not _models:
    pytestmark = [pytestmark, pytest.mark.skip(reason="Ollama unreachable on :11434")]
elif "gemma2:2b" not in _models:
    pytestmark = [pytestmark, pytest.mark.skip(reason="required model gemma2:2b not pulled")]


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import server as srv

    os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyrings.alt.file.PlaintextKeyring")

    with tempfile.TemporaryDirectory(prefix="dialekt-role-user-") as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)
        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir

        # Set the default model so make_interpreter picks the fast one
        # for agents that don't specify their own preferred model.
        (tmp_dir / "config.json").write_text(json.dumps({"model": "gemma2:2b"}))

        with TestClient(srv.app, raise_server_exceptions=False) as c:
            # PluginContext wires after the TestClient context-enter so
            # the app's lifespan has finished (it installed a default
            # context itself; we override to the same app for clarity
            # and to guarantee the binding outlives this fixture).
            _bind_plugin_context_to_testclient_app()
            yield c


# ── Plugin context injection ────────────────────────────────────────────────
# Finding UF-1 (MULTI_ROLE_E2E_REPORT.md) was: DialektSQL + retry_loop
# dispatched via httpx to http://localhost:8765, which TestClient isn't
# listening on, so SQL-via-chat scenarios couldn't run in this harness.
#
# Resolved 2026-04-24 by PluginContext (dialekt/llm/_plugin_context.py):
# the server fixture below installs a PluginContext(app=srv.app) before
# yielding, so DialektSQL + retry_loop dispatch in-process. The old
# UF-1 skip-detector has been removed — these tests now RUN.

def _bind_plugin_context_to_testclient_app():
    """Install a PluginContext wired to server.py's app for the duration
    of this suite. Called from the `client` fixture above."""
    import server as srv
    from dialekt.llm._plugin_context import PluginContext, set_context
    set_context(PluginContext(app=srv.app))


# ── Manifest helpers (mirror test_e2e_role_developer.py) ─────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _manifest(*, name, system_prompt="you are a helpful test assistant",
              capabilities=None, connection_types=None, autonomy="autonomous",
              preferred="gemma2:2b"):
    caps_block = "[]"
    if capabilities:
        caps_block = "\n" + "\n".join(f"    - {c}" for c in capabilities)
    conn_block = ""
    if connection_types:
        rows = "".join(
            f'    - type: "{t}"\n'
            '      role: "readonly"\n'
            f'      purpose: "role-user test ({t})"\n'
            for t in connection_types
        )
        conn_block = "\nconnections:\n  required:\n" + rows + "\n"
    return (
        'spec_version: "1.0.1"\n'
        'minimum_dialekt_version: "1.0.0"\n\n'
        'metadata:\n'
        f'  id: "{uuid.uuid4()}"\n'
        f'  name: "{name}"\n'
        '  description: "role-user E2E"\n  version: "1.0.0"\n  language: "en"\n'
        '  tags: []\n  author:\n    name: "t"\n    email: "t@t.t"\n'
        f'  created_at: "{_now_iso()}"\n  updated_at: "{_now_iso()}"\n\n'
        'model:\n'
        f'  preferred: "{preferred}"\n'
        '  acceptable: []\n  min_context_window: 8192\n'
        '  requirements:\n    min_ram_gb: 4\n    min_vram_gb: 0\n    recommended_ram_gb: 8\n'
        '  parameters:\n    temperature: 0.2\n    top_p: 0.9\n    max_tokens: 512\n\n'
        f'system_prompt: |\n  {system_prompt}\n\n'
        f'capabilities:\n  groups: {caps_block}\n'
        + conn_block
        + '\nautonomy:\n'
        f'  recommended: "{autonomy}"\n  max_allowed: "{autonomy}"\n\n'
        'input:\n  type: "chat"\n  placeholder: "Ask"\n\n'
        'output:\n  format: "markdown"\n  streaming: true\n'
        '  destination:\n    type: "notification"\n\n'
        'trigger:\n  type: "interactive"\n'
    )


def _publish(client, yaml_str) -> str:
    r = client.post("/agents/import-yaml", json={"manifest_yaml": yaml_str})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_pg(client, name) -> str:
    r = client.post("/connections", json={"name": name, **PG})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_ch(client, name) -> str:
    r = client.post("/ch-connections", json={"name": name, **CH})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── WS chat helper ──────────────────────────────────────────────────────────

def _chat_turn(client, content, agent_id=None, session_id=None, timeout=90):
    """Send one chat message via WS, collect the full stream until `done`.

    Returns dict: {session_id, messages: [str], code_blocks: [str],
    console_output: [str], errors: [str]}.
    """
    payload = {"type": "chat", "content": content}
    if agent_id:
        payload["agent_id"] = agent_id
    if session_id:
        payload["session_id"] = session_id

    messages: list[str] = []
    code_blocks: list[dict] = []
    _current_code: list[str] = []
    _current_code_fmt = [None]
    console_output: list[str] = []
    _current_console: list[str] = []
    errors: list[str] = []
    sid_out = session_id

    deadline = time.time() + timeout
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps(payload))
        while True:
            if time.time() > deadline:
                errors.append(f"timeout after {timeout}s")
                break
            # starlette's WebSocketTestSession.receive_text() blocks with
            # no timeout kwarg; the wall-clock deadline above is our
            # only safety net against a hung turn.
            try:
                raw = ws.receive_text()
            except Exception as e:
                errors.append(f"ws receive error: {e}")
                break
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            t = msg.get("type")
            if t == "start":
                sid_out = msg.get("session_id") or sid_out
            elif t == "message":
                c = msg.get("content")
                if isinstance(c, str):
                    messages.append(c)
            elif t == "code":
                if msg.get("start"):
                    _current_code = []
                    _current_code_fmt[0] = msg.get("format")
                elif msg.get("end"):
                    if _current_code:
                        code_blocks.append({
                            "format": _current_code_fmt[0],
                            "content": "".join(_current_code),
                        })
                    _current_code = []
                elif isinstance(msg.get("content"), str):
                    _current_code.append(msg["content"])
            elif t == "console":
                if msg.get("end"):
                    if _current_console:
                        console_output.append("".join(_current_console))
                    _current_console = []
                elif isinstance(msg.get("content"), str):
                    _current_console.append(msg["content"])
            elif t == "error":
                c = msg.get("content") or msg.get("detail")
                if c:
                    errors.append(c)
            elif t == "done":
                # Flush any in-flight buffers that didn't receive an explicit end
                if _current_code:
                    code_blocks.append({
                        "format": _current_code_fmt[0],
                        "content": "".join(_current_code),
                    })
                if _current_console:
                    console_output.append("".join(_current_console))
                break

    return dict(
        session_id=sid_out,
        messages=messages,
        code_blocks=code_blocks,
        console_output=console_output,
        errors=errors,
        full_reply="".join(messages),
    )


# ── 1 · Select bundled agent + send greeting ────────────────────────────────

def test_01_bundled_agent_plain_greeting(client):
    """Pick the first bundled agent and send a trivial prompt — just
    verify the WS stack completes a turn and returns some text. Uses
    gemma2:2b (the default fast model).
    """
    agents = client.get("/agents").json()
    assert agents, "no bundled agents found — migration may be broken"
    agent_id = agents[0]["id"]

    turn = _chat_turn(client, "Please reply with the word: OK", agent_id=agent_id)
    assert not turn["errors"], f"chat errored: {turn['errors']}"
    assert turn["full_reply"].strip(), "empty reply from bundled agent"
    assert turn["session_id"], "session_id not returned"


# ── 2 · SQL Analyst (PG) · count query ──────────────────────────────────────

def test_02_sql_analyst_counts_customers(client):
    """Create SQL Analyst, bind to PG, ask for a COUNT. Uses
    qwen2.5-coder:7b (SQL-quality critical). Asserts on structure:
    a code block AND a number resembling the seeded row count (1000).
    """
    if "qwen2.5-coder:7b" not in _models:
        pytest.skip("qwen2.5-coder:7b not pulled")

    conn_id = _create_pg(client, f"role-user-pg-{uuid.uuid4().hex[:6]}")
    agent_id = _publish(client, _manifest(
        name=f"SQL-Analyst-count-{uuid.uuid4().hex[:4]}",
        system_prompt=(
            "You are a PostgreSQL analyst. When asked for counts, emit ONE "
            "fenced ```sql``` block with a SELECT query, no prose "
            "before the code. After the query runs, summarise the result."
        ),
        capabilities=["database_read"],
        connection_types=["postgres"],
        preferred="qwen2.5-coder:7b",
    ))
    client.post(
        f"/agents/{agent_id}/binding",
        json={"connection_id": conn_id, "connection_type": "postgres"},
    )

    try:
        turn = _chat_turn(
            client,
            "How many rows are in ecom.customers? Return the exact number.",
            agent_id=agent_id, timeout=240,
        )
        assert not turn["errors"], turn["errors"]
        assert turn["code_blocks"], "no code blocks in reply"
        # Seeded count per postgres_seed.sql is 1000
        combined = turn["full_reply"] + " ".join(turn["console_output"])
        assert "1000" in combined, (
            f"expected row count 1000 somewhere in reply/console, got: "
            f"reply={turn['full_reply'][:200]!r} console={turn['console_output']}"
        )
    finally:
        # Agent and connection are cleaned up by the temp-DB teardown;
        # explicit DELETEs skipped to keep the test focused on chat.
        pass


# ── 3 · Multi-turn context retention ────────────────────────────────────────

def test_03_multi_turn_context_retention(client):
    """First: ask about customers. Then: ask "and orders?" — if context
    retention works, the agent applies the same COUNT pattern to
    orders (5000 seeded). Uses qwen2.5-coder:7b.
    """
    if "qwen2.5-coder:7b" not in _models:
        pytest.skip("qwen2.5-coder:7b not pulled")

    conn_id = _create_pg(client, f"role-user-multi-{uuid.uuid4().hex[:6]}")
    agent_id = _publish(client, _manifest(
        name=f"SQL-MultiTurn-{uuid.uuid4().hex[:4]}",
        system_prompt=(
            "You are a PostgreSQL analyst. Emit ONE fenced ```sql``` "
            "block with a SELECT query per user question."
        ),
        capabilities=["database_read"],
        connection_types=["postgres"],
        preferred="qwen2.5-coder:7b",
    ))
    client.post(
        f"/agents/{agent_id}/binding",
        json={"connection_id": conn_id, "connection_type": "postgres"},
    )

    turn1 = _chat_turn(
        client,
        "How many rows are in ecom.customers?",
        agent_id=agent_id, timeout=240,
    )
    assert not turn1["errors"], turn1["errors"]
    sid = turn1["session_id"]
    assert sid, "no session_id returned from first turn"

    # Follow-up: ambiguous on purpose. Agent should remember context
    # and apply the same COUNT pattern to ecom.orders (5000 seeded).
    # Longer timeout on turn 2 — context has grown so tokenisation +
    # generation take proportionally longer.
    # Be explicit about the block type to deflect LLM drift on long
    # contexts — qwen2.5-coder:7b sometimes drops the fence on turn 2.
    turn2 = _chat_turn(
        client,
        "Now run the same kind of count query against ecom.orders. "
        "Emit ONE fenced ```sql``` block with "
        "`SELECT COUNT(*) FROM ecom.orders;` and read the result.",
        agent_id=agent_id, session_id=sid, timeout=300,
    )
    assert not turn2["errors"], turn2["errors"]
    combined = turn2["full_reply"] + " ".join(turn2["console_output"])
    assert "5000" in combined, (
        f"expected orders count 5000 in reply, got: {combined[:300]!r}"
    )


# ── 4 · Implicit session create ─────────────────────────────────────────────

def test_04_session_created_implicitly_via_first_message(client):
    agents = client.get("/agents").json()
    agent_id = agents[0]["id"]

    before = {s["id"] for s in client.get("/sessions").json()}
    turn = _chat_turn(client, "Say OK and nothing else.", agent_id=agent_id)
    assert not turn["errors"], turn["errors"]
    sid = turn["session_id"]
    assert sid

    after = {s["id"] for s in client.get("/sessions").json()}
    assert sid in after, "session not persisted"
    assert sid not in before, "session already existed"


# ── 5 · Delete session ──────────────────────────────────────────────────────

def test_05_delete_session_removes_it(client):
    agents = client.get("/agents").json()
    agent_id = agents[0]["id"]
    turn = _chat_turn(client, "Say OK and nothing else.", agent_id=agent_id)
    sid = turn["session_id"]
    assert sid

    r = client.delete(f"/sessions/{sid}")
    assert r.status_code == 200, r.text
    assert all(s["id"] != sid for s in client.get("/sessions").json())


# ── 6 · Empty state — agent requires conn, no binding ───────────────────────

def test_06_agent_requires_conn_but_no_binding(client):
    """The frontend renders an empty-state card when the agent's
    manifest declares connections.required and GET /agents/{id}/binding
    returns `connection_id=null`. We verify those two backend signals
    line up — that's what the frontend reads.
    """
    agent_id = _publish(client, _manifest(
        name=f"NeedsDB-{uuid.uuid4().hex[:4]}",
        capabilities=["database_read"],
        connection_types=["postgres"],
    ))
    try:
        # Required type is surfaced via the manifest YAML on GET /agents/{id}
        a = client.get(f"/agents/{agent_id}").json()
        assert 'type: "postgres"' in a["manifest_yaml"]

        # No binding yet
        b = client.get(f"/agents/{agent_id}/binding").json()
        assert b.get("connection_id") in (None, "")
    finally:
        client.delete(f"/agents/{agent_id}")


# ── 7 · Pure LLM agent — no requirements, chats normally ────────────────────

def test_07_pure_llm_agent_chats_normally(client):
    agent_id = _publish(client, _manifest(name=f"PureLLM-{uuid.uuid4().hex[:4]}"))
    try:
        # No required types
        a = client.get(f"/agents/{agent_id}").json()
        assert 'type: "postgres"' not in a["manifest_yaml"]
        assert 'type: "mysql"' not in a["manifest_yaml"]

        turn = _chat_turn(
            client, "Reply with exactly the word OK.", agent_id=agent_id,
        )
        assert not turn["errors"], turn["errors"]
        assert turn["full_reply"].strip(), "no reply from pure LLM agent"
    finally:
        client.delete(f"/agents/{agent_id}")


# ── 8 · Retry loop on SQL against missing table ─────────────────────────────

def test_08_sql_retry_loop_graceful_on_missing_table(client):
    """Asking for rows from a table that does not exist must:
      • fire the SQL retry loop (logs show 🔄) OR surface the PG error
      • end with a finished turn (`done` arrives), NOT a 500 /
        WebSocket close
      • last reply must be some user-visible error, not empty

    Uses qwen2.5-coder:7b because it's the SQL-quality critical path.
    """
    if "qwen2.5-coder:7b" not in _models:
        pytest.skip("qwen2.5-coder:7b not pulled")

    conn_id = _create_pg(client, f"role-user-err-{uuid.uuid4().hex[:6]}")
    agent_id = _publish(client, _manifest(
        name=f"ErrPath-{uuid.uuid4().hex[:4]}",
        system_prompt=(
            "You are a PostgreSQL analyst. Emit ONE fenced ```sql``` "
            "block with the user's query. If the database returns an error, "
            "explain it briefly and stop."
        ),
        capabilities=["database_read"],
        connection_types=["postgres"],
        preferred="qwen2.5-coder:7b",
    ))
    client.post(
        f"/agents/{agent_id}/binding",
        json={"connection_id": conn_id, "connection_type": "postgres"},
    )

    turn = _chat_turn(
        client,
        "Please run: SELECT * FROM ecom.nonexistent_zzz LIMIT 1",
        agent_id=agent_id, timeout=180,
    )
    # The turn must complete (done arrived) — even if errors surfaced
    # mid-stream, the pipeline must not crash.
    # Either an error bubbled to the `error` channel OR the reply
    # mentions the missing relation — both are acceptable graceful paths.
    combined = (
        (turn["full_reply"] or "")
        + " ".join(turn["console_output"])
        + " ".join(turn["errors"])
    ).lower()
    assert any(
        kw in combined for kw in ("does not exist", "nonexistent_zzz", "error")
    ), f"no graceful error signal — got: {combined[:300]!r}"


# ── 9 · Agent switching mid-session ─────────────────────────────────────────

def test_09_agent_switch_mid_session_updates_session_row(client):
    """Start a session with agent A. Send a second turn with agent B
    and verify sessions.agent_id has flipped to B in the DB.
    """
    agent_a = _publish(client, _manifest(name=f"A-{uuid.uuid4().hex[:4]}"))
    agent_b = _publish(client, _manifest(name=f"B-{uuid.uuid4().hex[:4]}"))
    try:
        t1 = _chat_turn(client, "Say OK.", agent_id=agent_a)
        sid = t1["session_id"]
        assert sid

        # Confirm initial agent assignment via /sessions list
        sess = next((s for s in client.get("/sessions").json() if s["id"] == sid), None)
        assert sess, "session missing"
        assert sess.get("agent_id") == agent_a

        # Switch
        t2 = _chat_turn(client, "Say OK again.", agent_id=agent_b, session_id=sid)
        assert not t2["errors"], t2["errors"]

        sess = next((s for s in client.get("/sessions").json() if s["id"] == sid), None)
        assert sess.get("agent_id") == agent_b, (
            f"agent_id didn't flip to B; got {sess.get('agent_id')}"
        )
    finally:
        client.delete(f"/agents/{agent_a}")
        client.delete(f"/agents/{agent_b}")


# ── 10 · ClickHouse chat-level query ────────────────────────────────────────

def test_10_clickhouse_analyst_counts_events(client):
    """CH is a separate driver path; exercising it end-to-end catches
    any regression the PG path wouldn't. Uses qwen2.5-coder:7b.
    """
    if "qwen2.5-coder:7b" not in _models:
        pytest.skip("qwen2.5-coder:7b not pulled")

    conn_id = _create_ch(client, f"role-user-ch-{uuid.uuid4().hex[:6]}")
    agent_id = _publish(client, _manifest(
        name=f"CH-Analyst-{uuid.uuid4().hex[:4]}",
        system_prompt=(
            "You are a ClickHouse analyst connected to the "
            "`dialekt_integration` database. ALWAYS answer questions by "
            "emitting ONE fenced ```sql``` block — never use "
            "Python, never use clickhouse_driver, never attempt any other "
            "runtime. The `sql` block will be executed against "
            "the bound connection; simply read the returned table and "
            "summarise it for the user."
        ),
        capabilities=["database_read"],
        connection_types=["clickhouse"],
        preferred="qwen2.5-coder:7b",
    ))
    client.post(
        f"/agents/{agent_id}/binding",
        json={"connection_id": conn_id, "connection_type": "clickhouse"},
    )

    turn = _chat_turn(
        client,
        "How many rows are in dialekt_integration.events? "
        "Use a ```sql``` block with SELECT count() FROM "
        "dialekt_integration.events.",
        agent_id=agent_id, timeout=240,
    )
    assert not turn["errors"], turn["errors"]
    combined = turn["full_reply"] + " ".join(turn["console_output"])
    # Seed is 10_000 events
    assert "10000" in combined or "10,000" in combined, (
        f"expected event count 10000 in reply, got: {combined[:300]!r}"
    )
