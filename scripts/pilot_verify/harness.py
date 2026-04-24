"""Pilot-readiness verification harness for dialekt v0.10.0.

Creates connections, imports agent manifests, binds, runs WebSocket
chat sessions, and writes evidence.json with real LLM output.

Usage:
    python scripts/pilot_verify/harness.py

Every step is idempotent-ish: existing connections/agents with matching
names are reused instead of re-created.
"""
from __future__ import annotations

import json
import os
import sys
import time
import asyncio
import traceback
from pathlib import Path
from typing import Optional

import httpx
import websockets

BASE = os.environ.get("DIALEKT_BACKEND_URL", "http://localhost:8765")
WS_URL = BASE.replace("http://", "ws://").replace("https://", "wss://") + "/ws"

EVIDENCE_PATH = Path(__file__).parent / "evidence.json"
MANIFESTS_DIR = Path(__file__).parent / "manifests"

# Per-session timeout (seconds). LLM turns can be slow on 2B models.
WS_TIMEOUT = 180

# ── Helpers ──────────────────────────────────────────────────────────────────


def _http() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=30)


def ensure_connection(client: httpx.Client, prefix: str, spec: dict) -> str:
    """Return existing connection id matching spec['name'], or create one."""
    r = client.get(prefix)
    r.raise_for_status()
    for c in r.json():
        if c["name"] == spec["name"]:
            return c["id"]
    r = client.post(prefix, json=spec)
    r.raise_for_status()
    return r.json()["id"]


def ensure_agent(client: httpx.Client, manifest_yaml: str, name: str) -> str:
    """Return existing agent id matching name, or import from manifest."""
    r = client.get("/agents")
    r.raise_for_status()
    for a in r.json():
        if a["name"] == name:
            return a["id"]
    r = client.post("/agents/import-yaml",
                    json={"manifest_yaml": manifest_yaml, "status": "published"})
    r.raise_for_status()
    return r.json()["id"]


def bind(client: httpx.Client, agent_id: str, connection_id: Optional[str],
         connection_type: str = "postgres") -> None:
    if connection_id is None:
        return
    r = client.post(f"/agents/{agent_id}/binding",
                    json={"connection_id": connection_id,
                          "connection_type": connection_type})
    r.raise_for_status()


async def run_session(agent_id: str, messages: list[str], model: str) -> dict:
    """Open a WS session, send messages sequentially, collect all events."""
    session_id: Optional[str] = None
    turns = []
    t0 = time.time()
    try:
        async with websockets.connect(WS_URL, open_timeout=10,
                                       max_size=8 * 1024 * 1024) as ws:
            # Set model explicitly (otherwise backend default applies)
            await ws.send(json.dumps({"type": "model", "model": model}))
            # Set autonomy to auto-write (classic dialekt default)
            await ws.send(json.dumps({"type": "autonomy", "level": "ask-write"}))

            for m_idx, user_text in enumerate(messages):
                turn = {"user": user_text, "events": [], "final_text": "",
                        "code_blocks": [], "console_output": [], "errors": []}

                payload = {"type": "chat", "content": user_text,
                           "agent_id": agent_id}
                if session_id is not None:
                    payload["session_id"] = session_id

                await ws.send(json.dumps(payload))

                # Consume events until "done"
                t_turn = time.time()
                current_code = ""
                current_console = ""
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                    except asyncio.TimeoutError:
                        turn["errors"].append(
                            f"TIMEOUT after {WS_TIMEOUT}s on turn {m_idx}")
                        break
                    evt = json.loads(raw)
                    t = evt.get("type")

                    if t == "start":
                        if session_id is None:
                            session_id = evt.get("session_id")
                    elif t == "message":
                        if evt.get("role") == "assistant":
                            c = evt.get("content", "")
                            if isinstance(c, str):
                                turn["final_text"] += c
                    elif t == "code":
                        if evt.get("start"):
                            current_code = ""
                        elif isinstance(evt.get("content"), str):
                            current_code += evt["content"]
                        elif evt.get("end") and current_code:
                            turn["code_blocks"].append({
                                "format": evt.get("format"),
                                "content": current_code,
                            })
                            current_code = ""
                    elif t == "console":
                        if isinstance(evt.get("content"), str):
                            current_console += evt["content"]
                        elif evt.get("end") and current_console:
                            turn["console_output"].append(current_console)
                            current_console = ""
                    elif t == "error":
                        turn["errors"].append(evt.get("content", ""))
                    elif t == "done":
                        break
                    elif t == "model_ok" or t == "autonomy_ok":
                        pass

                # Flush any trailing console buffer
                if current_console:
                    turn["console_output"].append(current_console)

                turn["wall_seconds"] = round(time.time() - t_turn, 2)
                turns.append(turn)
    except Exception as e:
        return {"session_id": session_id, "turns": turns,
                "session_error": f"{type(e).__name__}: {e}",
                "wall_seconds": round(time.time() - t0, 2)}
    return {"session_id": session_id, "turns": turns, "session_error": None,
            "wall_seconds": round(time.time() - t0, 2)}


# ── Catalog definitions ──────────────────────────────────────────────────────


MODELS = {
    "sql": "qwen2.5-coder:7b",
    "code": "qwen2.5-coder:7b",
    "doc": "gemma3-12b:latest",
    "chat": "gemma3-12b:latest",
    "tiny": "gemma2:2b",
}


# Each entry: {category, name, manifest_yaml, connection_prefix, conn_spec,
#              messages, model}
def _manifest(name: str, description: str, system_prompt: str,
              caps: list[str], *, language: str = "multi",
              connections: Optional[list[dict]] = None,
              variables: Optional[dict] = None,
              autonomy: str = "ask-before-write",
              preferred_model: str = "qwen2.5-coder:7b") -> str:
    import uuid as _uuid
    import yaml as _yaml
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    m = {
        "spec_version": "1.0.1",
        "minimum_dialekt_version": "1.0.0",
        "metadata": {
            "id": str(_uuid.uuid4()),
            "name": name,
            "description": description,
            "version": "1.0.0",
            "language": language,
            "tags": ["pilot-catalog"],
            "author": {"name": "dialekt.ai", "email": "hello@dias.now"},
            "created_at": now,
            "updated_at": now,
        },
        "model": {
            "preferred": preferred_model,
            "acceptable": ["gemma3-12b:latest", "gemma2:2b"],
            "min_context_window": 8192,
            "requirements": {
                "min_ram_gb": 8,
                "min_vram_gb": 4,
                "recommended_ram_gb": 16,
            },
            "parameters": {
                "temperature": 0.2,
                "top_p": 0.9,
                "max_tokens": 2048,
            },
        },
        "system_prompt": system_prompt,
        "autonomy": {"recommended": autonomy, "max_allowed": "autonomous"},
        "capabilities": {"groups": caps, "exceptions": []},
        "trigger": {"type": "interactive"},
        "input": {"type": "chat"},
        "output": {
            "format": "markdown",
            "streaming": True,
            "destination": {"type": "notification"},
        },
    }
    if connections:
        m["connections"] = {"required": connections}
    if variables:
        m["variables"] = variables
    return _yaml.safe_dump(m, sort_keys=False, allow_unicode=True)


def build_catalog():
    """Return a list of catalog entries — runtime-built so we can emit YAML
    manifests deterministically.
    """
    # ── SQL agents ──
    pg_sa_prompt = """You are PG Sales Analyst — a read-only PostgreSQL assistant.
Connection ID: {{connection_id}}
Always respond in the same language as the user.

Write valid PostgreSQL SQL in ```sql fenced blocks. dialekt will
execute them automatically against the bound connection.

SCHEMA HINT: all tables live in schema `ecom` (customers, products,
orders, order_items). Use qualified names like ecom.customers.

Keep queries focused: exactly ONE ```sql block per response. After
dialekt returns results, explain them in 1-2 sentences.
"""
    mysql_prompt = """You are MySQL Inventory Analyst — a read-only MySQL assistant.
Connection ID: {{connection_id}}

Write valid MySQL SQL in ```sql fenced blocks (no EXPLAIN prefix — just SELECT).
Tables are UNQUALIFIED: customers, products, orders, order_items.

Keep responses compact: one query, then a one-line explanation of the result.
Respond in the user's language.
"""
    ch_prompt = """You are ClickHouse Events Analyst — a read-only ClickHouse assistant.
Connection ID: {{connection_id}}

Write valid ClickHouse SQL in ```sql blocks. Tables live in the
default database: customers, orders, products, events.

Use clickhouse-specific functions where helpful (countIf, groupArray, etc).
Keep it to ONE query per response. Respond in the user's language.
"""

    return [
        # ── Category 1: SQL ──
        {
            "category": "SQL Analytics",
            "name": "PG Sales Analyst",
            "manifest_yaml": _manifest(
                "PG Sales Analyst",
                "Read-only PostgreSQL sales/customers analyst. RU+EN.",
                pg_sa_prompt,
                caps=["database_read"],
                connections=[{"type": "postgres",
                               "role": "readonly",
                               "purpose": "Sales DB (ecom schema)"}],
                variables={"connection_id": {"type": "string", "required": True,
                                              "description": "dialekt PG conn id"}},
            ),
            "connection_prefix": "/connections",
            "connection_type": "postgres",
            "conn_spec": {"name": "Pilot PG Integration",
                          "type": "postgresql",
                          "host": "127.0.0.1", "port": 15432,
                          "database": "dialekt_integration",
                          "username": "dialekt_test",
                          "password": "dialekt_test",
                          "row_limit": 500},
            "messages": [
                "Сколько у нас всего клиентов?",
                "Топ-5 стран по количеству клиентов",
            ],
            "model": MODELS["sql"],
        },
        {
            "category": "SQL Analytics",
            "name": "MySQL Inventory Analyst",
            "manifest_yaml": _manifest(
                "MySQL Inventory Analyst",
                "Read-only MySQL inventory/products analyst.",
                mysql_prompt,
                caps=["database_read"],
                connections=[{"type": "mysql",
                               "role": "readonly",
                               "purpose": "Inventory DB"}],
                variables={"connection_id": {"type": "string", "required": True,
                                              "description": "dialekt MySQL conn id"}},
            ),
            "connection_prefix": "/mysql-connections",
            "connection_type": "mysql",
            "conn_spec": {"name": "Pilot MySQL Integration",
                          "type": "mysql",
                          "host": "127.0.0.1", "port": 13306,
                          "database": "dialekt_integration",
                          "username": "dialekt_test",
                          "password": "dialekt_test",
                          "row_limit": 500},
            "messages": [
                "How many products do we have in total?",
                "Which product category has the most items in stock?",
            ],
            "model": MODELS["sql"],
        },
        {
            "category": "SQL Analytics",
            "name": "ClickHouse Events Analyst",
            "manifest_yaml": _manifest(
                "ClickHouse Events Analyst",
                "Read-only ClickHouse analytics assistant.",
                ch_prompt,
                caps=["database_read"],
                connections=[{"type": "clickhouse",
                               "role": "readonly",
                               "purpose": "Events analytics"}],
                variables={"connection_id": {"type": "string", "required": True,
                                              "description": "dialekt CH conn id"}},
            ),
            "connection_prefix": "/ch-connections",
            "connection_type": "clickhouse",
            "conn_spec": {"name": "Pilot CH Integration",
                          "type": "clickhouse",
                          "host": "127.0.0.1", "port": 18123,
                          "database": "dialekt_integration",
                          "username": "dialekt_test",
                          "password": "dialekt_test",
                          "row_limit": 500},
            "messages": [
                "How many total events do we have?",
                "What are the top-3 event_type values by count?",
            ],
            "model": MODELS["sql"],
        },

        # ── Category 2: Code ──
        {
            "category": "Code Assistants",
            "name": "Python Code Reviewer",
            "manifest_yaml": _manifest(
                "Python Code Reviewer",
                "Python code review with suggestions. Uses filesystem_read to inspect nearby files.",
                (
                    "You are Python Code Reviewer. When the user shows a "
                    "Python snippet, review it and suggest concrete "
                    "improvements in 3-5 bullet points. Focus on: naming, "
                    "error handling, complexity, and obvious bugs. "
                    "If asked to explain code, be brief (under 120 words)."
                ),
                caps=["filesystem_read"],
                language="en",
            ),
            "connection_prefix": None,
            "connection_type": None,
            "conn_spec": None,
            "messages": [
                ("Review this Python snippet:\n"
                 "```python\n"
                 "def div(a,b):\n"
                 "    return a/b\n"
                 "```"),
            ],
            "model": MODELS["code"],
        },
        {
            "category": "Code Assistants",
            "name": "Bash Script Helper",
            "manifest_yaml": _manifest(
                "Bash Script Helper",
                "Explains shell commands; suggests safer equivalents.",
                (
                    "You are Bash Script Helper. Given a user's task or a "
                    "command, respond with: (1) the exact shell command "
                    "in a ```bash block, (2) one-sentence explanation. "
                    "Do NOT execute — just show commands. Keep it short."
                ),
                caps=["shell_execute"],
                language="en",
                autonomy="review-only",
            ),
            "connection_prefix": None,
            "connection_type": None,
            "conn_spec": None,
            "messages": [
                "How do I find the 5 largest files in my home directory?",
            ],
            "model": MODELS["code"],
        },

        # ── Category 3: Documents ──
        {
            "category": "Document Processing",
            "name": "Document Summarizer",
            "manifest_yaml": _manifest(
                "Document Summarizer",
                "Summarizes English or Russian text into 3 bullet points.",
                (
                    "You are Document Summarizer. Summarize the user's "
                    "text into exactly 3 bullet points. No preamble, no "
                    "closing. Match the user's language."
                ),
                caps=[],
                language="multi",
            ),
            "connection_prefix": None,
            "connection_type": None,
            "conn_spec": None,
            "messages": [
                ("Summarize:\n"
                 "dialekt is a local AI agent desktop application. "
                 "Unlike cloud-based assistants, it runs entirely on the "
                 "user's machine using Ollama models. It can query "
                 "PostgreSQL, MySQL, and ClickHouse databases via the "
                 "bundled SQL Analyst agent. Data never leaves the device."),
            ],
            "model": MODELS["doc"],
        },
        {
            "category": "Document Processing",
            "name": "Translator RU-EN-KK",
            "manifest_yaml": _manifest(
                "Translator RU-EN-KK",
                "Translator for Russian, English, Kazakh.",
                (
                    "You are a translator. Translate the user's text into "
                    "the target language they specify (RU, EN, or KK). "
                    "Output ONLY the translation, nothing else. If target "
                    "is ambiguous, assume English."
                ),
                caps=[],
                language="kk",
            ),
            "connection_prefix": None,
            "connection_type": None,
            "conn_spec": None,
            "messages": [
                "Translate to Kazakh: 'Good morning, how are you today?'",
            ],
            "model": MODELS["doc"],
        },

        # ── Category 4: Conversation ──
        {
            "category": "Conversation",
            "name": "General Assistant (bundled)",
            "manifest_yaml": None,  # already exists — just use existing
            "existing_agent_name": "General Assistant",
            "connection_prefix": None,
            "connection_type": None,
            "conn_spec": None,
            "messages": [
                "What can you help me with? Keep it to 3 bullet points.",
            ],
            "model": MODELS["chat"],
        },
        {
            "category": "Conversation",
            "name": "Russian Writing Assistant",
            "manifest_yaml": _manifest(
                "Russian Writing Assistant",
                "Помощник по русскому языку — переписывает тексты, проверяет грамматику.",
                (
                    "Вы — помощник по русскому языку. Переписывайте "
                    "тексты пользователя чтобы они звучали грамотнее и "
                    "естественнее. Отвечайте на русском, кратко."
                ),
                caps=[],
                language="ru",
            ),
            "connection_prefix": None,
            "connection_type": None,
            "conn_spec": None,
            "messages": [
                "Перепиши лучше: 'Мы делаем продукт который очень полезный для команд'",
            ],
            "model": MODELS["chat"],
        },

        # ── Category 5: Multi-tool ──
        {
            "category": "Multi-tool",
            "name": "Data Engineer Helper",
            "manifest_yaml": _manifest(
                "Data Engineer Helper",
                "Multi-tool DE agent: DB + filesystem + shell.",
                (
                    "You are a Data Engineer helper with access to "
                    "PostgreSQL, the local filesystem, and a shell. "
                    "Connection ID: {{connection_id}}.\n"
                    "When the user asks for data, prefer SQL via a "
                    "```sql block. For quick system checks use ```bash. "
                    "Keep responses to ONE tool call per turn."
                ),
                caps=["database_read", "filesystem_read", "shell_execute"],
                connections=[{"type": "postgres",
                               "role": "readonly",
                               "purpose": "Data warehouse"}],
                variables={
                    "connection_id": {"type": "string", "required": True,
                                      "description": "PG conn id"},
                    "report_dir": {"type": "string", "required": False,
                                    "description": "Where to stash report files (default: /tmp)"},
                },
                autonomy="ask-before-write",
            ),
            "connection_prefix": "/connections",
            "connection_type": "postgres",
            # Reuse the PG integration conn we create earlier — this
            # entry is later patched to point at that id.
            "conn_reuse": "PG Sales Analyst",
            "messages": [
                "How many distinct countries are represented in the customers table?",
            ],
            "model": MODELS["sql"],
        },
    ]


# ── Main ─────────────────────────────────────────────────────────────────────


async def main():
    catalog = build_catalog()
    evidence = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "backend": BASE,
        "agents": [],
    }

    with _http() as client:
        # First pass: ensure all connections, then agents, then bindings.
        # Remember mapping name -> connection_id for "conn_reuse".
        conn_ids: dict[str, str] = {}

        for entry in catalog:
            if entry.get("conn_spec"):
                try:
                    cid = ensure_connection(client,
                                             entry["connection_prefix"],
                                             entry["conn_spec"])
                    conn_ids[entry["name"]] = cid
                    entry["_connection_id"] = cid
                    print(f"[conn] {entry['name']} -> {cid}")
                except Exception as e:
                    entry["_connection_id"] = None
                    entry["_connection_error"] = str(e)
                    print(f"[conn] {entry['name']} FAILED: {e}")
            elif entry.get("conn_reuse"):
                reused = conn_ids.get(entry["conn_reuse"])
                entry["_connection_id"] = reused
                entry["connection_prefix"] = "/connections"
                entry["connection_type"] = "postgres"
                print(f"[conn] {entry['name']} reuses {entry['conn_reuse']} -> {reused}")
            else:
                entry["_connection_id"] = None

        for entry in catalog:
            try:
                if entry.get("manifest_yaml"):
                    aid = ensure_agent(client, entry["manifest_yaml"],
                                        entry["name"])
                else:
                    # Look up existing by name
                    r = client.get("/agents")
                    r.raise_for_status()
                    aid = next((a["id"] for a in r.json()
                                if a["name"] == entry["existing_agent_name"]),
                                None)
                    if aid is None:
                        raise RuntimeError(
                            f"existing agent {entry['existing_agent_name']!r} not found")
                entry["_agent_id"] = aid
                print(f"[agent] {entry['name']} -> {aid}")

                if entry.get("_connection_id"):
                    bind(client, aid, entry["_connection_id"],
                         connection_type=entry["connection_type"])
                    print(f"[bind]  {entry['name']} ← {entry['_connection_id']}")
            except Exception as e:
                entry["_agent_error"] = str(e)
                print(f"[agent] {entry['name']} FAILED: {e}")

    # Second pass: WS sessions
    for entry in catalog:
        aid = entry.get("_agent_id")
        if not aid:
            evidence["agents"].append({
                "name": entry["name"],
                "category": entry["category"],
                "status": "setup_failed",
                "error": entry.get("_agent_error") or entry.get("_connection_error"),
            })
            continue

        print(f"[ws]    {entry['name']} — {len(entry['messages'])} turn(s) "
              f"on {entry['model']} ...")
        try:
            result = await run_session(aid, entry["messages"], entry["model"])
        except Exception as e:
            result = {"session_error": f"{type(e).__name__}: {e}",
                      "turns": [], "traceback": traceback.format_exc()}

        ok_turns = [t for t in result.get("turns", [])
                    if not t.get("errors") and (t.get("final_text")
                                                  or t.get("code_blocks")
                                                  or t.get("console_output"))]
        status = ("ok" if (not result.get("session_error")
                            and len(ok_turns) == len(entry["messages"]))
                    else "partial" if ok_turns else "failed")

        evidence["agents"].append({
            "name": entry["name"],
            "category": entry["category"],
            "agent_id": aid,
            "connection_id": entry.get("_connection_id"),
            "connection_type": entry.get("connection_type"),
            "model": entry["model"],
            "status": status,
            "turns_expected": len(entry["messages"]),
            "turns_ok": len(ok_turns),
            "session_error": result.get("session_error"),
            "wall_seconds": result.get("wall_seconds"),
            "turns": [
                {
                    "user": t["user"],
                    "final_text": (t.get("final_text") or "")[:3000],
                    "code_blocks": [
                        {"format": cb["format"],
                          "content": cb["content"][:1500]}
                        for cb in t.get("code_blocks", [])
                    ],
                    "console_output": [c[:1500] for c in t.get("console_output", [])],
                    "errors": t.get("errors", []),
                    "wall_seconds": t.get("wall_seconds"),
                }
                for t in result.get("turns", [])
            ],
        })
        print(f"[ws]    {entry['name']} => {status} "
              f"({len(ok_turns)}/{len(entry['messages'])} turns)")

    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
    print(f"\nWrote {EVIDENCE_PATH}")
    # Summary
    by_status: dict[str, int] = {}
    for a in evidence["agents"]:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
    print(f"Summary: {by_status}")


if __name__ == "__main__":
    asyncio.run(main())
