"""
dialekt.ai — FastAPI + Open Interpreter backend
WebSocket at /ws  — streaming chat (includes session_id in start event)
REST:
  GET  /health
  POST /ollama/start
  GET  /sessions
  GET  /sessions/{id}/messages
  DELETE /sessions/{id}
"""
import asyncio
import base64
import builtins as _builtins
import getpass
import json
import logging
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# ── Runtime constants (derived from environment, never hardcoded) ─────────────

_USERNAME = getpass.getuser()
_HOME = Path.home()

# ── Config & settings ─────────────────────────────────────────────────────────

DIALEKT_DIR = _HOME / ".dialekt"
SETTINGS_FILE = DIALEKT_DIR / "config.json"
OLD_SETTINGS_FILE = _HOME / ".config" / "dialekt" / "settings.json"  # migration source

DEFAULT_SETTINGS: dict = {
    "model": "gemma3-12b",
    "cloud_api_url": "https://api.dialekt.ai",
    "cloud_bearer_token": None,
    "tenant_info": None,
    "user_info": None,
    "system_prompt": (
        f"You are dialekt — a powerful local AI agent with full access to this computer "
        f"(user: {_USERNAME}).\n"
        "You can read/write files, run shell commands, open browsers, and control the desktop.\n\n"
        "CRITICAL RULE — HOW TO RUN CODE:\n"
        "ALWAYS use fenced markdown code blocks to execute commands. NEVER use JSON.\n"
        "Examples:\n```shell\nls ~/Desktop\n```\n```python\nprint('hello')\n```\n"
        "Always explain briefly what you'll do, then the code block, then show results.\n"
        f"Desktop path: {_HOME}/Desktop\n\n"
        "LOCAL AI GENERATION TOOLS (use via Python httpx/requests):\n"
        "• Image generation (Flux Schnell):\n"
        "  POST http://localhost:8765/comfy/txt2img\n"
        "  Body: {\"prompt\": \"...\", \"width\": 1024, \"height\": 1024, \"steps\": 4, \"seed\": -1}\n"
        "  Returns: {\"ok\": true, \"files\": [\"/abs/path/image.png\"]}\n"
        "  Fast (~10-30s). ComfyUI auto-starts if needed.\n"
        "• Video generation (LTX-Video 2.3, 22B):\n"
        "  POST http://localhost:8765/comfy/txt2vid\n"
        "  Body: {\"prompt\": \"...\", \"width\": 704, \"height\": 416, \"frames\": 97, \"steps\": 8, \"seed\": -1}\n"
        "  Returns: {\"ok\": true, \"files\": [\"/abs/path/video.mp4\"]}\n"
        "  WARNING: takes 5-20 minutes. Tell the user before running.\n"
        "• ComfyUI status: GET http://localhost:8765/comfy/status\n\n"
        "Example Python usage:\n"
        "```python\nimport httpx\nr = httpx.post('http://localhost:8765/comfy/txt2img',\n"
        "               json={'prompt': 'a cat on a mountain'}, timeout=300)\nprint(r.json())\n```"
    ),
    "autonomy": "ask-write",
    "temperature": 0.7,
    "context_window": 8192,
    "max_tokens": 4096,
}


def load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            stored = json.loads(SETTINGS_FILE.read_text())
            return {**DEFAULT_SETTINGS, **stored}
        # Migrate from old ~/.config/dialekt/settings.json location
        if OLD_SETTINGS_FILE.exists():
            stored = json.loads(OLD_SETTINGS_FILE.read_text())
            merged = {**DEFAULT_SETTINGS, **stored}
            save_settings(merged)
            log.info("Migrated settings from ~/.config/dialekt/ to ~/.dialekt/")
            return merged
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()


def save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


import aiosqlite
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dialekt")

DB_PATH = DIALEKT_DIR / "dialekt.db"
db: aiosqlite.Connection = None
_active_interpreters: dict = {}  # ws_id → interpreter instance

_SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'postgresql',
    host       TEXT NOT NULL,
    port       INTEGER NOT NULL DEFAULT 5432,
    database   TEXT NOT NULL,
    username   TEXT NOT NULL,
    row_limit  INTEGER NOT NULL DEFAULT 1000,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    manifest_yaml TEXT,
    version       TEXT NOT NULL DEFAULT '1.0.0',
    status        TEXT NOT NULL DEFAULT 'draft',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    agent_id      TEXT REFERENCES agents(id) ON DELETE SET NULL,
    model         TEXT NOT NULL DEFAULT 'gemma3-12b',
    title         TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    type       TEXT NOT NULL,
    format     TEXT,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_bindings (
    agent_id        TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    connection_id   TEXT,
    connection_type TEXT NOT NULL DEFAULT 'postgres',
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def _init_db():
    await db.executescript(_SCHEMA)
    await db.commit()


async def _migrate_agents():
    """Idempotent: add agent_id column to sessions, seed General Assistant agent."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    cols = [row[1] for row in await cursor.fetchall()]
    if "agent_id" not in cols:
        await db.execute(
            "ALTER TABLE sessions ADD COLUMN agent_id TEXT REFERENCES agents(id) ON DELETE SET NULL"
        )
        log.info("Migration: added agent_id column to sessions")

    cursor = await db.execute("SELECT id FROM agents WHERE name = 'General Assistant' LIMIT 1")
    row = await cursor.fetchone()
    if row is None:
        ga_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO agents (id, name, description, system_prompt, status) VALUES (?,?,?,?,?)",
            (ga_id, "General Assistant",
             "Default dialekt agent with full computer access",
             DEFAULT_SETTINGS["system_prompt"], "published"),
        )
        log.info(f"Migration: created General Assistant agent {ga_id}")
    else:
        ga_id = row[0]

    await db.execute("UPDATE sessions SET agent_id = ? WHERE agent_id IS NULL", (ga_id,))

    # Auto-import SQL Analyst if not yet present
    cursor = await db.execute("SELECT id FROM agents WHERE name = 'SQL Analyst' LIMIT 1")
    if await cursor.fetchone() is None:
        await _maybe_import_bundled_agent(
            Path(__file__).parent.parent / "agents" / "sql_analyst" / "manifest.yaml"
        )

    await db.commit()
    log.info("Migration: agents ready")


async def _maybe_import_bundled_agent(manifest_path: Path) -> None:
    """Import a bundled agent manifest if the file exists. Errors are logged only."""
    if not manifest_path.exists():
        return
    try:
        from dialekt_manifest import ManifestValidator
        yaml_str = manifest_path.read_text()
        result = ManifestValidator().validate_string(yaml_str)
        if not result.valid:
            log.warning(f"Bundled manifest {manifest_path.name} failed validation: {result.errors}")
            return
        m = result.manifest
        await db.execute(
            "INSERT OR IGNORE INTO agents (id, name, description, system_prompt, manifest_yaml, version, status)"
            " VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), m.metadata.name, m.metadata.description or "",
             m.system_prompt or "", yaml_str, m.metadata.version, "published"),
        )
        log.info(f"Bundled agent '{m.metadata.name}' imported")
    except Exception as e:
        log.warning(f"Could not import bundled agent {manifest_path.name}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await _init_db()
    await _migrate_agents()
    from mcp_servers.postgres_mcp import init_db as pg_init_db
    from mcp_servers.mysql_mcp import init_db as mysql_init_db
    from mcp_servers.clickhouse_mcp import init_db as ch_init_db
    pg_init_db(db)
    mysql_init_db(db)
    ch_init_db(db)
    log.info(f"SQLite ready at {DB_PATH}")
    # Non-blocking: warn if embedding model isn't pulled yet
    from mcp_servers import schema_rag as _rag
    asyncio.create_task(_rag.check_model())
    yield
    from mcp_servers.postgres_mcp import close_all_pools
    from mcp_servers.mysql_mcp import close_all_pools_mysql
    await close_all_pools()
    await close_all_pools_mysql()
    await db.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from mcp_servers.postgres_mcp import router as pg_router  # noqa: E402
from mcp_servers.mysql_mcp import router as mysql_router  # noqa: E402
from mcp_servers.clickhouse_mcp import router as ch_router  # noqa: E402
app.include_router(pg_router)
app.include_router(mysql_router)
app.include_router(ch_router)


# ── Confirmation intercept ────────────────────────────────────────────────────
# Maps thread_ident → {event, approved, send_fn, loop, last_code}
_thread_confirm: dict = {}
_orig_input = _builtins.input


def _dialekt_input(prompt=""):
    """Replaces builtins.input so OI threads route confirmation through WS."""
    state = _thread_confirm.get(threading.current_thread().ident)
    if state is None:
        return _orig_input(prompt)
    code_preview = state.get("last_code", "")
    asyncio.run_coroutine_threadsafe(
        state["send"]({
            "type": "confirmation",
            "content": str(prompt) or "Run this code?",
            "code": code_preview,
        }),
        state["loop"],
    ).result(timeout=5)
    state["event"].clear()
    state["event"].wait(timeout=180)   # 3-minute user timeout
    return "y" if state["approved"][0] else "n"


_builtins.input = _dialekt_input


# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_create_session(model: str | None = None, agent_id: str | None = None) -> str:
    sid = str(uuid.uuid4())
    s = load_settings()
    m = model or s.get("model", "gemma3-12b")
    await db.execute(
        "INSERT INTO sessions(id, agent_id, model) VALUES(?,?,?)",
        (sid, agent_id, m),
    )
    await db.commit()
    return sid


async def db_set_title(session_id: str, title: str):
    await db.execute(
        "UPDATE sessions SET title=?, updated_at=datetime('now') WHERE id=?",
        (title[:120], session_id),
    )
    await db.commit()


async def db_save_message(session_id: str, role: str, type_: str,
                          content: str, format_: str = None) -> str:
    mid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages(id, session_id, role, type, format, content) VALUES(?,?,?,?,?,?)",
        (mid, session_id, role, type_, format_, content),
    )
    await db.execute(
        "UPDATE sessions SET message_count = message_count + 1, updated_at = datetime('now') WHERE id = ?",
        (session_id,),
    )
    await db.commit()
    return mid


# ── Agent DB helpers ─────────────────────────────────────────────────────────

async def db_create_agent(name: str, description: str, system_prompt: str,
                          manifest_yaml: str | None = None,
                          version: str = "1.0.0",
                          status: str = "draft") -> str:
    agent_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO agents (id, name, description, system_prompt, manifest_yaml, version, status)"
        " VALUES (?,?,?,?,?,?,?)",
        (agent_id, name, description, system_prompt, manifest_yaml, version, status),
    )
    await db.commit()
    return agent_id


async def db_get_agent(agent_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def db_list_agents() -> list[dict]:
    cursor = await db.execute("SELECT * FROM agents ORDER BY updated_at DESC")
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def db_update_agent(agent_id: str, **fields) -> None:
    allowed = {"name", "description", "system_prompt", "manifest_yaml", "version", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    set_parts = [f"{k} = ?" for k in updates] + ["updated_at = datetime('now')"]
    await db.execute(
        f"UPDATE agents SET {', '.join(set_parts)} WHERE id = ?",
        [*updates.values(), agent_id],
    )
    await db.commit()


async def db_delete_agent(agent_id: str) -> None:
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    await db.commit()


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/system")
async def system_stats():
    """Real-time CPU / RAM / disk stats."""
    import psutil
    cpu = psutil.cpu_percent(interval=0.1)
    vm  = psutil.virtual_memory()
    dsk = psutil.disk_usage('/')
    try:
        import subprocess
        gpu = int(subprocess.check_output(
            ['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
            timeout=1, stderr=subprocess.DEVNULL,
        ).decode().strip().split('\n')[0])
    except Exception:
        gpu = None
    return {
        "cpu": round(cpu),
        "ram": round(vm.percent),
        "gpu": gpu,
        "disk": round(dsk.percent),
    }


@app.get("/about")
async def about():
    import platform
    return {
        "version": "0.8.2",
        "username": _USERNAME,
        "home": str(_HOME),
        "platform": platform.system(),
        "platform_version": platform.version(),
        "db": str(DB_PATH),
        "config": str(SETTINGS_FILE),
    }


# ── Admin endpoints ──────────────────────────────────────────────────────────

@app.get("/admin/stats")
async def admin_stats():
    """Aggregate stats for the admin panel."""
    cur = await db.execute("SELECT COUNT(*) FROM sessions")
    session_count = (await cur.fetchone())[0]
    cur = await db.execute("SELECT COUNT(*) FROM agents")
    agent_count = (await cur.fetchone())[0]
    cur = await db.execute("SELECT COUNT(*) FROM connections")
    connection_count = (await cur.fetchone())[0]
    cur = await db.execute("SELECT COUNT(*) FROM messages")
    message_count = (await cur.fetchone())[0]
    cur = await db.execute(
        "SELECT a.name, a.status, COUNT(s.id) AS session_count "
        "FROM agents a LEFT JOIN sessions s ON s.agent_id = a.id "
        "GROUP BY a.id ORDER BY session_count DESC"
    )
    agents = [dict(r) for r in await cur.fetchall()]
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "sessions": session_count,
        "agents": agent_count,
        "connections": connection_count,
        "messages": message_count,
        "db_size_bytes": db_size,
        "agents_detail": agents,
    }


# ── Cloud sync endpoints (skeleton — requires dialekt Cloud) ─────────────────

@app.get("/schema-rag/model-status")
async def schema_rag_model_status():
    """Check whether the embedding model is available in Ollama."""
    from mcp_servers import schema_rag as _rag
    available = await _rag.check_model()
    return {
        "model": _rag.EMBED_MODEL,
        "available": available,
        "pull_command": f"ollama pull {_rag.EMBED_MODEL}" if not available else None,
    }


@app.post("/schema-rag/pull-model")
async def schema_rag_pull_model():
    """Pull the embedding model from Ollama (may take several minutes)."""
    from mcp_servers import schema_rag as _rag
    ok = await _rag.pull_model()
    return {"ok": ok, "model": _rag.EMBED_MODEL}


@app.get("/sync/status")
async def sync_status():
    s = load_settings()
    api_key = s.get("cloud_api_key", "")
    if not api_key:
        return {"enabled": False, "message": "Cloud sync not configured. Add your dialekt Cloud API key in Settings → Cloud Sync."}
    return {"enabled": True, "api_key_prefix": api_key[:8] + "…", "last_sync": s.get("last_sync"), "pending": True}


@app.post("/sync/configure")
async def sync_configure(body: dict):
    from fastapi import HTTPException
    key = (body.get("api_key") or "").strip()
    if not key:
        raise HTTPException(400, "api_key is required")
    s = load_settings()
    s["cloud_api_key"] = key
    save_settings(s)
    return {"ok": True, "message": "Cloud API key saved."}


@app.post("/sync/push")
async def sync_push():
    s = load_settings()
    if not s.get("cloud_api_key"):
        from fastapi import HTTPException
        raise HTTPException(402, "Cloud sync not configured. Add API key via POST /sync/configure.")
    return {"ok": True, "pushed": 0, "message": "Cloud sync push — not yet implemented in this build."}


@app.post("/sync/pull")
async def sync_pull():
    import httpx
    from fastapi import HTTPException
    s = load_settings()
    token = s.get("cloud_bearer_token")
    if not token:
        # Legacy: cloud_api_key configured but no bearer token yet
        if s.get("cloud_api_key"):
            return {"ok": True, "pulled": 0, "message": "Validate your license key to enable agent sync."}
        raise HTTPException(402, "No cloud bearer token. Validate your license first.")
    cloud_url = s.get("cloud_api_url", "https://api.dialekt.ai")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{cloud_url}/agents/assigned-to-me",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code == 401:
            raise HTTPException(401, "Cloud token expired. Re-validate your license key.")
        r.raise_for_status()
        remote_agents = r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Cloud unreachable: {e}")

    import yaml as _yaml
    pulled = 0
    for ra in remote_agents:
        manifest_yaml = ra.get("manifest_yaml") or ""
        parsed = {}
        if manifest_yaml:
            try:
                parsed = _yaml.safe_load(manifest_yaml) or {}
            except Exception:
                parsed = {}
        md = parsed.get("metadata") or {}
        name = md.get("name") or ra.get("name") or "Unnamed Agent"
        cursor = await db.execute("SELECT id FROM agents WHERE name = ?", (name,))
        existing = await cursor.fetchone()
        if existing:
            continue
        await db_create_agent(
            name=name,
            description=md.get("description") or ra.get("description") or "",
            system_prompt=parsed.get("system_prompt") or "",
            manifest_yaml=manifest_yaml or None,
            version=md.get("version") or ra.get("version") or "1.0.0",
            status="published",
        )
        pulled += 1

    # Update last sync timestamp
    s["last_sync"] = __import__("datetime").datetime.utcnow().isoformat()
    save_settings(s)
    return {"ok": True, "pulled": pulled, "total_remote": len(remote_agents)}


# ── License endpoints ─────────────────────────────────────────────────────────

@app.get("/license/status")
async def license_status():
    import time
    s = load_settings()
    key = s.get("license_key")
    trial_started = s.get("trial_started")
    trial_valid = False
    if trial_started:
        trial_valid = (time.time() - trial_started) < 30 * 86400
    return {
        "valid": bool(key) or trial_valid,
        "license_key": key,
        "trial": bool(trial_started),
        "trial_valid": trial_valid,
        "tenant": s.get("tenant_info"),
    }


@app.post("/license/save")
async def license_save(body: dict):
    s = load_settings()
    if body.get("license_key"):
        s["license_key"] = body["license_key"]
    if body.get("tenant"):
        s["tenant_info"] = body["tenant"]
    if body.get("user"):
        s["user_info"] = body["user"]
    if body.get("bearer_token"):
        s["cloud_bearer_token"] = body["bearer_token"]
    save_settings(s)
    return {"ok": True}


@app.post("/license/trial")
async def license_trial():
    import time
    s = load_settings()
    if not s.get("trial_started"):
        s["trial_started"] = time.time()
    save_settings(s)
    return {"ok": True, "expires_in_days": 30}


# ── Agent endpoints ───────────────────────────────────────────────────────────

@app.get("/agents")
async def list_agents_endpoint():
    return await db_list_agents()


@app.post("/agents", status_code=201)
async def create_agent_endpoint(body: dict):
    from fastapi import HTTPException
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    agent_id = await db_create_agent(
        name=name,
        description=body.get("description", ""),
        system_prompt=body.get("system_prompt", ""),
        manifest_yaml=body.get("manifest_yaml"),
        version=body.get("version", "1.0.0"),
    )
    return {"id": agent_id, "name": name}


@app.get("/agents/{agent_id}")
async def get_agent_endpoint(agent_id: str):
    from fastapi import HTTPException
    agent = await db_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@app.patch("/agents/{agent_id}")
async def update_agent_endpoint(agent_id: str, body: dict):
    from fastapi import HTTPException
    if not await db_get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    await db_update_agent(agent_id, **body)
    return {"ok": True}


@app.delete("/agents/{agent_id}")
async def delete_agent_endpoint(agent_id: str):
    from fastapi import HTTPException
    if not await db_get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    await db_delete_agent(agent_id)
    return {"ok": True}


@app.post("/agents/import")
async def import_agent_endpoint(file: UploadFile = File(...)):
    from fastapi import HTTPException
    from dialekt_manifest import ManifestValidator
    yaml_str = (await file.read()).decode("utf-8")
    result = ManifestValidator().validate_string(yaml_str)
    if not result.valid:
        raise HTTPException(422, detail={
            "errors": [{"code": e.code.value, "message": e.message} for e in result.errors]
        })
    m = result.manifest
    name = m.metadata.name
    description = m.metadata.description or ""
    system_prompt = m.system_prompt or ""
    version = m.metadata.version
    agent_id = await db_create_agent(
        name=name,
        description=description,
        system_prompt=system_prompt,
        manifest_yaml=yaml_str,
        version=version,
    )
    warnings = [{"code": w.code.value, "message": w.message} for w in result.warnings]
    return {"id": agent_id, "name": name, "warnings": warnings}


@app.post("/agents/import-yaml", status_code=201)
async def import_agent_yaml_endpoint(body: dict):
    """Import agent from YAML string (used by the builder wizard)."""
    from fastapi import HTTPException
    from dialekt_manifest import ManifestValidator
    yaml_str = (body.get("manifest_yaml") or "").strip()
    if not yaml_str:
        raise HTTPException(400, "manifest_yaml is required")
    status = body.get("status", "draft")
    if status not in ("draft", "published"):
        status = "draft"
    result = ManifestValidator().validate_string(yaml_str)
    if not result.valid:
        raise HTTPException(422, detail={
            "errors": [{"code": e.code.value, "message": e.message} for e in result.errors]
        })
    m = result.manifest
    agent_id = await db_create_agent(
        name=m.metadata.name,
        description=m.metadata.description or "",
        system_prompt=m.system_prompt or "",
        manifest_yaml=yaml_str,
        version=m.metadata.version,
        status=status,
    )
    warnings = [{"code": w.code.value, "message": w.message} for w in result.warnings]
    return {"id": agent_id, "name": m.metadata.name, "warnings": warnings}


@app.get("/agents/{agent_id}/export")
async def export_agent_endpoint(agent_id: str):
    from fastapi import HTTPException
    from fastapi.responses import Response
    agent = await db_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    yaml_content = agent.get("manifest_yaml") or ""
    safe_name = agent["name"].replace(" ", "_")
    return Response(
        content=yaml_content,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.agent.yaml"'},
    )


# ── Agent connection binding ──────────────────────────────────────────────────

@app.get("/agents/{agent_id}/binding")
async def get_agent_binding(agent_id: str):
    from fastapi import HTTPException
    agent = await db_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    cursor = await db.execute(
        "SELECT connection_id, connection_type FROM agent_bindings WHERE agent_id = ?",
        (agent_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return {"agent_id": agent_id, "connection_id": None, "connection_type": None}
    return {"agent_id": agent_id, "connection_id": row[0], "connection_type": row[1]}


@app.post("/agents/{agent_id}/binding")
async def set_agent_binding(agent_id: str, body: dict):
    from fastapi import HTTPException
    agent = await db_get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    conn_id = body.get("connection_id")
    conn_type = body.get("connection_type", "postgres")
    if conn_id is None:
        await db.execute("DELETE FROM agent_bindings WHERE agent_id = ?", (agent_id,))
    else:
        await db.execute(
            "INSERT OR REPLACE INTO agent_bindings(agent_id, connection_id, connection_type) VALUES (?,?,?)",
            (agent_id, conn_id, conn_type),
        )
    await db.commit()
    return {"ok": True, "agent_id": agent_id, "connection_id": conn_id}


@app.delete("/agents/{agent_id}/binding")
async def delete_agent_binding(agent_id: str):
    await db.execute("DELETE FROM agent_bindings WHERE agent_id = ?", (agent_id,))
    await db.commit()
    return {"ok": True}


# ── Mode config endpoints ─────────────────────────────────────────────────────

@app.get("/config/mode")
async def get_mode():
    s = load_settings()
    return {"mode": s.get("mode", "builder")}


@app.post("/config/mode")
async def set_mode(body: dict):
    from fastapi import HTTPException
    mode = body.get("mode", "builder")
    if mode not in ("builder", "user"):
        raise HTTPException(400, "mode must be 'builder' or 'user'")
    s = load_settings()
    s["mode"] = mode
    save_settings(s)
    return {"ok": True, "mode": mode}


@app.post("/model")
async def set_model(body: dict):
    model = body.get("model", "gemma3-12b")
    return {"status": "ok", "model": model}


@app.get("/health")
async def health():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get("http://localhost:11434/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
        return {"status": "ok", "ollama": True, "models": models}
    except Exception as e:
        return {"status": "degraded", "ollama": False, "error": str(e)}


@app.post("/ollama/start")
async def ollama_start():
    import subprocess
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"status": "starting"}
    except FileNotFoundError:
        return {"status": "error", "error": "ollama binary not found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/ollama/check")
async def ollama_check():
    import subprocess, shutil, httpx, platform
    installed = shutil.which("ollama") is not None
    version: str | None = None
    running = False
    if installed:
        try:
            result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=3)
            version = result.stdout.strip().split()[-1] if result.returncode == 0 else None
        except Exception:
            pass
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get("http://localhost:11434/api/tags")
                running = r.status_code == 200
        except Exception:
            running = False
    sys_platform = platform.system().lower()
    platform_map = {"darwin": "Mac", "linux": "Linux", "windows": "Windows"}
    install_url = "https://ollama.com/download/" + platform_map.get(sys_platform, "Mac")
    return {
        "installed": installed,
        "running": running,
        "version": version,
        "install_url": install_url,
        "platform": sys_platform,
    }


@app.get("/sessions")
async def list_sessions():
    cursor = await db.execute(
        "SELECT id, agent_id, title, model, created_at, updated_at, message_count "
        "FROM sessions ORDER BY updated_at DESC LIMIT 50"
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": r["id"],
            "agent_id": r["agent_id"],
            "title": r["title"],
            "model": r["model"],
            "message_count": r["message_count"],
            "updated_at": r["updated_at"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    cursor = await db.execute(
        "SELECT id, role, type, format, content, created_at "
        "FROM messages WHERE session_id=? ORDER BY created_at",
        (session_id,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "type": r["type"],
            "format": r["format"],
            "content": r["content"],
            "ts": r["created_at"],
        }
        for r in rows
    ]


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    await db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    await db.commit()
    return {"status": "deleted"}


@app.patch("/sessions/{session_id}")
async def rename_session(session_id: str, body: dict):
    title = (body.get("title") or "").strip()
    if not title:
        from fastapi import HTTPException
        raise HTTPException(400, "title required")
    await db.execute(
        "UPDATE sessions SET title=?, updated_at=datetime('now') WHERE id=?",
        (title[:120], session_id),
    )
    await db.commit()
    return {"ok": True, "title": title}


@app.post("/terminal")
async def open_terminal():
    import subprocess as sp
    try:
        env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
        for term in ["xterm", "gnome-terminal", "konsole", "xfce4-terminal"]:
            try:
                sp.Popen([term], env=env, start_new_session=True,
                         stdout=sp.DEVNULL, stderr=sp.DEVNULL)
                return {"ok": True, "terminal": term}
            except FileNotFoundError:
                continue
        return {"ok": False, "error": "no terminal emulator found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ComfyUI output path — configurable via environment, defaults to ~/projects/ml/ComfyUI/output
_comfy_output_env = os.environ.get("DIALEKT_COMFY_OUTPUT")
COMFY_OUTPUT = Path(_comfy_output_env) if _comfy_output_env else _HOME / "projects" / "ml" / "ComfyUI" / "output"


@app.get("/files")
async def serve_file(path: str):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    p = Path(path).resolve()
    allowed = [
        COMFY_OUTPUT.resolve(),
        Path("/tmp/dialekt_files").resolve(),
    ]
    if not any(str(p).startswith(str(a)) for a in allowed):
        raise HTTPException(403, "path not allowed")
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    import time
    os.makedirs("/tmp/dialekt_files", exist_ok=True)
    ts = int(time.time())
    safe = (file.filename or "upload.bin").replace("/", "_")
    path = f"/tmp/dialekt_files/{ts}_{safe}"
    with open(path, "wb") as f:
        f.write(await file.read())
    return {"path": path, "name": safe}


@app.get("/settings")
async def get_settings_endpoint():
    return load_settings()


@app.post("/settings")
async def post_settings(body: dict):
    s = load_settings()
    s.update(body)
    save_settings(s)
    for itp in list(_active_interpreters.values()):
        try:
            if "model" in body:
                itp.llm.model = f"ollama_chat/{body['model']}"
            if "temperature" in body:
                itp.llm.temperature = float(body["temperature"])
            if "context_window" in body:
                itp.llm.context_window = int(body["context_window"])
            if "max_tokens" in body:
                itp.llm.max_tokens = int(body["max_tokens"])
            if "system_prompt" in body:
                itp.system_message = body["system_prompt"]
            if "autonomy" in body:
                _apply_autonomy(itp, body["autonomy"])
        except Exception:
            pass
    return {"ok": True}


@app.delete("/sessions")
async def wipe_all_sessions():
    await db.execute("DELETE FROM sessions")
    await db.commit()
    return {"ok": True}


@app.get("/ollama/pull/stream")
async def ollama_pull_stream(model: str):
    import httpx

    async def generate():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST", "http://localhost:11434/api/pull",
                    json={"name": model, "stream": True},
                ) as r:
                    async for line in r.aiter_lines():
                        if line.strip():
                            yield f"data: {line}\n\n"
        except Exception as e:
            yield f'data: {{"error": "{str(e)}"}}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── ComfyUI integration ───────────────────────────────────────────────────────

COMFY_URL = os.environ.get("DIALEKT_COMFY_URL", "http://127.0.0.1:8188")

_comfy_main_env = os.environ.get("DIALEKT_COMFY_MAIN")
COMFY_MAIN   = Path(_comfy_main_env) if _comfy_main_env else _HOME / "projects" / "ml" / "ComfyUI" / "main.py"

_comfy_python_env = os.environ.get("DIALEKT_COMFY_PYTHON")
COMFY_PYTHON = Path(_comfy_python_env) if _comfy_python_env else _HOME / "projects" / "ml" / "ComfyUI" / "venv" / "bin" / "python3.12"


def _flux_workflow(prompt: str, width: int, height: int, steps: int, seed: int) -> dict:
    return {
        "1":  {"class_type": "UnetLoaderGGUF",
               "inputs": {"unet_name": "flux1-schnell-Q5_K_S.gguf"}},
        "2":  {"class_type": "DualCLIPLoaderGGUF",
               "inputs": {"clip_name1": "clip_l.safetensors",
                          "clip_name2": "t5-v1_1-xxl-encoder-Q5_K_M.gguf",
                          "type": "flux"}},
        "3":  {"class_type": "VAELoader",
               "inputs": {"vae_name": "ae.safetensors"}},
        "4":  {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["2", 0], "text": prompt}},
        "5":  {"class_type": "EmptySD3LatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6":  {"class_type": "BasicGuider",
               "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
        "7":  {"class_type": "BasicScheduler",
               "inputs": {"model": ["1", 0], "scheduler": "simple",
                          "steps": steps, "denoise": 1.0}},
        "8":  {"class_type": "RandomNoise",  "inputs": {"noise_seed": seed}},
        "9":  {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "10": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["8", 0], "guider": ["6", 0],
                          "sampler": ["9", 0], "sigmas": ["7", 0],
                          "latent_image": ["5", 0]}},
        "11": {"class_type": "VAEDecode",
               "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "dialekt_img"}},
    }


def _ltxv_workflow(prompt: str, width: int, height: int, frames: int,
                   steps: int, seed: int) -> dict:
    neg = "low quality, blurry, distorted, cartoon, watermark, text"
    return {
        "1":  {"class_type": "UnetLoaderGGUF",
               "inputs": {"unet_name": "ltx-2.3-22b-dev-Q4_0.gguf"}},
        "2":  {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["1", 0],
                          "lora_name": "ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
                          "strength_model": 0.6}},
        "3":  {"class_type": "DualCLIPLoaderGGUF",
               "inputs": {"clip_name1": "gemma-3-12b-it-Q4_K_M.gguf",
                          "clip_name2": "ltx-2.3_text_projection_bf16.safetensors",
                          "type": "ltxv"}},
        "4":  {"class_type": "VAELoader",
               "inputs": {"vae_name": "LTX23_video_vae_bf16.safetensors"}},
        "5":  {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["3", 0], "text": prompt}},
        "6":  {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["3", 0], "text": neg}},
        "7":  {"class_type": "EmptyLTXVLatentVideo",
               "inputs": {"width": width, "height": height,
                          "length": frames, "batch_size": 1}},
        "8":  {"class_type": "LTXVConditioning",
               "inputs": {"positive": ["5", 0], "negative": ["6", 0],
                          "frame_rate": 24.0}},
        "9":  {"class_type": "LTXVScheduler",
               "inputs": {"steps": steps, "max_shift": 2.05, "base_shift": 0.95,
                          "stretch": True, "terminal": 0.1, "latent": ["7", 0]}},
        "10": {"class_type": "KSamplerSelect",
               "inputs": {"sampler_name": "euler_ancestral_cfg_pp"}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "12": {"class_type": "CFGGuider",
               "inputs": {"model": ["2", 0], "positive": ["8", 0],
                          "negative": ["8", 1], "cfg": 1.0}},
        "13": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["11", 0], "guider": ["12", 0],
                          "sampler": ["10", 0], "sigmas": ["9", 0],
                          "latent_image": ["7", 0]}},
        "14": {"class_type": "LTXVTiledVAEDecode",
               "inputs": {"vae": ["4", 0], "latents": ["13", 0],
                          "horizontal_tiles": 2, "vertical_tiles": 2,
                          "overlap": 6, "last_frame_fix": False,
                          "working_device": "auto", "working_dtype": "auto"}},
        "15": {"class_type": "CreateVideo",
               "inputs": {"images": ["14", 0], "fps": 24.0}},
        "16": {"class_type": "SaveVideo",
               "inputs": {"video": ["15", 0], "filename_prefix": "dialekt_vid",
                          "format": "mp4", "codec": "h264"}},
    }


def _collect_files(outputs: dict) -> list:
    files = []
    for node_out in outputs.values():
        for key in ("images", "videos", "gifs"):
            for item in node_out.get(key, []):
                fn = item.get("filename", "")
                sf = item.get("subfolder", "")
                if fn:
                    p = COMFY_OUTPUT / sf / fn if sf else COMFY_OUTPUT / fn
                    files.append(str(p))
    return files


async def _comfy_ensure_running() -> dict | None:
    """Return None if running, or error dict if failed to start."""
    import httpx, subprocess
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            await c.get(f"{COMFY_URL}/system_stats")
        return None
    except Exception:
        pass
    if not COMFY_MAIN.exists() or not COMFY_PYTHON.exists():
        return {"ok": False, "error": "ComfyUI not found. Set DIALEKT_COMFY_MAIN and DIALEKT_COMFY_PYTHON env vars."}
    log.info("ComfyUI not running — starting...")
    subprocess.Popen(
        [str(COMFY_PYTHON), str(COMFY_MAIN),
         "--listen", "127.0.0.1", "--port", "8188"],
        cwd=str(COMFY_MAIN.parent),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(90):
        await asyncio.sleep(1)
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                await c.get(f"{COMFY_URL}/system_stats")
            log.info("ComfyUI ready")
            return None
        except Exception:
            pass
    return {"ok": False, "error": "ComfyUI did not start within 90 seconds"}


async def _comfy_run(workflow: dict, timeout: int = 1800) -> list:
    import httpx
    client_id = str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{COMFY_URL}/prompt",
                         json={"prompt": workflow, "client_id": client_id})
        r.raise_for_status()
        prompt_id = r.json()["prompt_id"]
    log.info(f"ComfyUI prompt_id={prompt_id}")
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(3)
        async with httpx.AsyncClient(timeout=10) as c:
            hist = (await c.get(f"{COMFY_URL}/history/{prompt_id}")).json()
        if prompt_id in hist:
            return _collect_files(hist[prompt_id].get("outputs", {}))
    raise TimeoutError(f"ComfyUI job timed out after {timeout}s")


@app.get("/comfy/status")
async def comfy_status():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{COMFY_URL}/system_stats")
        return {"running": True, "system": r.json()}
    except Exception:
        return {"running": False}


@app.post("/comfy/start")
async def comfy_start():
    err = await _comfy_ensure_running()
    if err:
        return err
    return {"ok": True, "status": "running"}


@app.post("/comfy/txt2img")
async def comfy_txt2img(body: dict):
    import random
    err = await _comfy_ensure_running()
    if err:
        return err
    prompt = body.get("prompt", "a beautiful landscape, photorealistic")
    width  = int(body.get("width",  1024))
    height = int(body.get("height", 1024))
    steps  = int(body.get("steps",  4))
    seed   = int(body.get("seed",   -1))
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
    try:
        wf    = _flux_workflow(prompt, width, height, steps, seed)
        files = await _comfy_run(wf, timeout=300)
        return {"ok": True, "files": files, "seed": seed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/comfy/txt2vid")
async def comfy_txt2vid(body: dict):
    import random
    err = await _comfy_ensure_running()
    if err:
        return err
    prompt = body.get("prompt", "a cinematic scene, photorealistic")
    width  = int(body.get("width",  704))
    height = int(body.get("height", 416))
    frames = int(body.get("frames", 97))
    steps  = int(body.get("steps",  8))
    seed   = int(body.get("seed",   -1))
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
    try:
        wf    = _ltxv_workflow(prompt, width, height, frames, steps, seed)
        files = await _comfy_run(wf, timeout=1800)
        return {"ok": True, "files": files, "seed": seed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── File / image context injection ───────────────────────────────────────────

async def describe_image_vision(path: str) -> str:
    """Call the best available ollama vision model to describe an image."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            tags = await c.get("http://localhost:11434/api/tags")
            models = [m["name"] for m in tags.json().get("models", [])]
        vision = next(
            (m for m in models if any(v in m.lower() for v in
             ["llava", "bakllava", "moondream", "minicpm", "qwen2-vl",
              "llama3.2", "gemma3"])),
            None,
        )
        if not vision:
            return f"[image at {path} — no vision model available; OI can read the file directly if needed]"
        img_b64 = base64.b64encode(Path(path).read_bytes()).decode()
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post("http://localhost:11434/api/generate", json={
                "model": vision,
                "prompt": (
                    "Describe this image in detail for a developer AI agent. "
                    "Include all visible text, UI elements, code, errors, data, and layout."
                ),
                "images": [img_b64],
                "stream": False,
            })
        desc = r.json().get("response", "")
        if desc:
            return f"[Screenshot described by {vision}]\n{desc}"
    except Exception as e:
        log.warning(f"Vision describe failed: {e}")
    return f"[image at {path}]"


async def preprocess_content(content: str) -> str:
    """Expand @file: and @screenshot: markers into actual file contents for OI context."""
    text_lines, attachments = [], []
    for line in content.split("\n"):
        m_file = re.match(r"^@file:(.+)$", line.strip())
        m_shot = re.match(r"^@screenshot:(.+)$", line.strip())
        if m_file:
            attachments.append(("file", m_file.group(1).strip()))
        elif m_shot:
            attachments.append(("screenshot", m_shot.group(1).strip()))
        else:
            text_lines.append(line)

    parts = []
    user_text = "\n".join(text_lines).strip()
    if user_text:
        parts.append(user_text)

    for kind, path in attachments:
        if kind == "file":
            try:
                raw = Path(path).read_bytes()
                try:
                    text = raw.decode("utf-8")
                    if len(text) > 60_000:
                        text = text[:60_000] + f"\n... [truncated — full file is {len(text)} chars]"
                    ext = Path(path).suffix.lstrip(".") or "text"
                    parts.append(f"--- {Path(path).name} ---\n```{ext}\n{text}\n```")
                except UnicodeDecodeError:
                    parts.append(f"--- {Path(path).name} --- [binary file, {len(raw)} bytes, path: {path}]")
            except Exception as e:
                parts.append(f"[cannot read {path}: {e}]")
        elif kind == "screenshot":
            desc = await describe_image_vision(path)
            parts.append(f"--- screenshot ---\n{desc}")

    return "\n\n".join(p.strip() for p in parts if p.strip())


# ── OI factory ────────────────────────────────────────────────────────────────

def _apply_autonomy(itp, level: str) -> None:
    if level in ("review", "ask"):
        itp.auto_run = False
        itp.safe_mode = "off"
    elif level == "ask-write":
        itp.auto_run = True
        itp.safe_mode = "ask"
    else:  # auto, yolo
        itp.auto_run = True
        itp.safe_mode = "off"


async def resolve_agent_context(agent: dict) -> dict:
    """
    For agents that reference {{connection_id}}: look up the bound connection,
    build substitution vars, and optionally run a Schema RAG search.
    Returns a dict with keys: connection_id, connection_name, database_type, schema_summary.
    """
    result = {"connection_id": None, "connection_name": None, "database_type": None, "schema_summary": None}
    agent_id = agent.get("id")
    if not agent_id:
        return result
    cursor = await db.execute(
        "SELECT connection_id, connection_type FROM agent_bindings WHERE agent_id = ?",
        (agent_id,),
    )
    row = await cursor.fetchone()
    if not row or not row[0]:
        return result
    conn_id, conn_type = row[0], row[1]
    result["connection_id"] = conn_id
    result["database_type"] = conn_type
    # Look up connection name
    cursor2 = await db.execute("SELECT name FROM connections WHERE id = ?", (conn_id,))
    conn_row = await cursor2.fetchone()
    if conn_row:
        result["connection_name"] = conn_row[0]
    return result


def make_interpreter(
    agent: dict | None = None,
    agent_context: dict | None = None,
    *,
    history_summary: str | None = None,
    few_shot_examples: list | None = None,
):
    from interpreter import interpreter
    from dialekt.llm.prompt_wrapper import (
        build_system_prompt, substitute_template_vars, should_wrap,
    )
    s = load_settings()
    interpreter.reset()
    model = s.get("model", "gemma3-12b")
    interpreter.llm.model = f"ollama_chat/{model}"
    interpreter.llm.api_base = "http://localhost:11434"
    interpreter.llm.context_window = int(s.get("context_window", 8192))
    interpreter.llm.max_tokens = int(s.get("max_tokens", 4096))
    interpreter.llm.temperature = float(s.get("temperature", 0.7))
    interpreter.llm.supports_functions = False
    interpreter.verbose = False

    if agent and agent.get("system_prompt"):
        raw_prompt = agent["system_prompt"]
        ctx = agent_context or {}
        # Substitute {{connection_id}} and related placeholders
        raw_prompt = substitute_template_vars(
            raw_prompt,
            connection_id=ctx.get("connection_id"),
            connection_name=ctx.get("connection_name"),
            database_type=ctx.get("database_type"),
        )
        manifest_yaml = agent.get("manifest_yaml", "")
        if should_wrap(manifest_yaml):
            # Extract language and output format from manifest if present
            lang = None
            out_fmt = None
            if manifest_yaml:
                import yaml as _yaml
                try:
                    m_data = _yaml.safe_load(manifest_yaml)
                    lang = (m_data.get("metadata") or {}).get("language")
                    out_fmt = (m_data.get("output") or {}).get("format")
                except Exception:
                    pass
            system_message = build_system_prompt(
                raw_prompt=raw_prompt,
                agent_name=agent.get("name", "Assistant"),
                language_hint=lang,
                output_format=out_fmt,
                schema_summary=ctx.get("schema_summary"),
                history_summary=history_summary,
                few_shot_examples=few_shot_examples,
                max_tokens=interpreter.llm.context_window,
            )
        else:
            system_message = raw_prompt
        interpreter.system_message = system_message
    else:
        interpreter.system_message = s.get("system_prompt", DEFAULT_SETTINGS["system_prompt"])

    _apply_autonomy(interpreter, s.get("autonomy", "ask-write"))
    return interpreter


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    log.info("WS connected")

    loop = asyncio.get_event_loop()
    itp = make_interpreter()
    ws_id = str(uuid.uuid4())
    _active_interpreters[ws_id] = itp
    session_id: str = None
    current_agent_id: str | None = None
    first_message = True
    stop_flag = threading.Event()
    confirm_event = threading.Event()
    confirm_approved = [False]

    async def send(obj):
        try:
            await ws.send_text(json.dumps(obj))
        except Exception:
            pass

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg.get("type") == "stop":
                stop_flag.set()
                await send({"type": "done"})
                continue

            if msg.get("type") == "confirm":
                confirm_approved[0] = msg.get("approved", False)
                confirm_event.set()
                continue

            if msg.get("type") == "model":
                model = msg.get("model", "gemma3-12b")
                itp.llm.model = f"ollama_chat/{model}"
                await send({"type": "model_ok", "model": model})
                continue

            if msg.get("type") == "autonomy":
                level = msg.get("level", "ask-write")
                if level == "ask":
                    itp.auto_run = False
                    itp.safe_mode = "off"
                elif level == "ask-write":
                    itp.auto_run = True
                    itp.safe_mode = "ask"
                else:
                    itp.auto_run = True
                    itp.safe_mode = "off"
                await send({"type": "autonomy_ok", "level": level})
                continue

            if msg.get("type") == "join":
                session_id = msg.get("session_id")
                cursor = await db.execute(
                    "SELECT agent_id FROM sessions WHERE id = ?", (session_id,)
                )
                sess_row = await cursor.fetchone()
                agent_for_join = None
                agent_ctx_for_join = None
                if sess_row and sess_row[0]:
                    agent_for_join = await db_get_agent(sess_row[0])
                    if agent_for_join:
                        agent_ctx_for_join = await resolve_agent_context(agent_for_join)

                # Load message history — used for both summarization and few-shot query
                cursor = await db.execute(
                    "SELECT role, content FROM messages WHERE session_id=? AND type='message' ORDER BY created_at",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                all_msgs = [{"role": r["role"], "type": "message", "content": r["content"]} for r in rows]

                # Goal 8.4: history summarization when session exceeds token budget
                from dialekt.llm.prompt_wrapper import summarize_history as _summarize_history
                TOKEN_BUDGET = 6000
                _token_est = lambda t: max(1, len(t) // 4)
                total_tokens = sum(_token_est(m["content"]) for m in all_msgs)
                history_sum_for_join = None
                recent_msgs = all_msgs
                if total_tokens > TOKEN_BUDGET:
                    split = max(0, len(all_msgs) - 10)
                    old_msgs = all_msgs[:split]
                    recent_msgs = all_msgs[split:]
                    if old_msgs:
                        history_sum_for_join = _summarize_history(old_msgs, max_chars=1500)

                # Goal 8.5: retrieve few-shot examples based on last user message
                few_shots_for_join = None
                if agent_for_join:
                    try:
                        from dialekt.llm.few_shot_memory import get_few_shots as _get_fs
                        user_msgs = [m for m in all_msgs if m["role"] == "user"]
                        query = user_msgs[-1]["content"] if user_msgs else agent_for_join.get("name", "")
                        few_shots_for_join = await _get_fs(agent_for_join["id"], query)
                    except Exception:
                        pass

                if agent_for_join:
                    current_agent_id = agent_for_join["id"]
                itp = make_interpreter(
                    agent_for_join, agent_ctx_for_join,
                    history_summary=history_sum_for_join,
                    few_shot_examples=few_shots_for_join,
                )
                _active_interpreters[ws_id] = itp
                itp.messages = recent_msgs
                await send({"type": "joined", "session_id": session_id})
                continue

            if msg.get("type") != "chat":
                continue

            content = msg.get("content", "").strip()
            if not content:
                continue

            if session_id is None:
                sid_from_client = msg.get("session_id")
                agent_id_for_session = msg.get("agent_id")
                if sid_from_client:
                    session_id = sid_from_client
                else:
                    session_id = await db_create_session(agent_id=agent_id_for_session)
                    if agent_id_for_session:
                        agent = await db_get_agent(agent_id_for_session)
                        if agent:
                            current_agent_id = agent["id"]
                            agent_ctx = await resolve_agent_context(agent)
                            itp = make_interpreter(agent, agent_ctx)
                            _active_interpreters[ws_id] = itp
                    first_message = True

            log.info(f"[{session_id[:8]}] User: {content[:80]}")

            await db_save_message(session_id, "user", "message", content)

            if first_message:
                plain = re.sub(r'@(file|screenshot):\S+', '', content).strip()
                await db_set_title(session_id, (plain or content)[:80])
                first_message = False

            oi_content = await preprocess_content(content)

            stop_flag.clear()
            confirm_event.clear()
            await send({"type": "start", "session_id": session_id})

            ai_text_buf = []
            code_buf = {"format": None, "content": []}
            console_buf = []

            def run_oi():
                nonlocal ai_text_buf, code_buf, console_buf
                tid = threading.current_thread().ident
                _thread_confirm[tid] = {
                    "event": confirm_event,
                    "approved": confirm_approved,
                    "send": send,
                    "loop": loop,
                    "last_code": "",
                }
                try:
                    for chunk in itp.chat(oi_content, stream=True, display=False):
                        if stop_flag.is_set():
                            break

                        log.info(f"OI chunk: {chunk!r}")

                        ctype = chunk.get("type", "")
                        crole = chunk.get("role", "")
                        ccontent = chunk.get("content", "")

                        if ctype in ("message", "code", "console", "error"):
                            asyncio.run_coroutine_threadsafe(send(chunk), loop).result(timeout=5)

                        if ctype == "message" and crole == "assistant":
                            if isinstance(ccontent, str):
                                ai_text_buf.append(ccontent)
                        elif ctype == "code":
                            if chunk.get("start"):
                                code_buf = {"format": chunk.get("format", "python"), "content": []}
                            elif isinstance(ccontent, str):
                                code_buf["content"].append(ccontent)
                            elif chunk.get("end") and code_buf["content"]:
                                code_str = "".join(code_buf["content"])
                                _thread_confirm[tid]["last_code"] = code_str
                                asyncio.run_coroutine_threadsafe(
                                    db_save_message(session_id, "assistant", "code",
                                                    code_str, code_buf["format"]),
                                    loop
                                ).result(timeout=5)
                        elif ctype == "console":
                            if isinstance(ccontent, str):
                                console_buf.append(ccontent)
                            elif chunk.get("end") and console_buf:
                                asyncio.run_coroutine_threadsafe(
                                    db_save_message(session_id, "tool", "console", "".join(console_buf)),
                                    loop
                                ).result(timeout=5)
                                console_buf = []

                except Exception as e:
                    asyncio.run_coroutine_threadsafe(
                        send({"type": "error", "content": str(e)}), loop
                    ).result(timeout=5)
                finally:
                    _thread_confirm.pop(tid, None)
                    final_answer = "".join(ai_text_buf)
                    if final_answer:
                        asyncio.run_coroutine_threadsafe(
                            db_save_message(session_id, "assistant", "message", final_answer),
                            loop
                        ).result(timeout=5)
                        # Goal 8.5: persist successful interaction for future few-shot retrieval
                        if current_agent_id and len(final_answer) > 20:
                            try:
                                from dialekt.llm.few_shot_memory import save_interaction as _save_fs
                                asyncio.run_coroutine_threadsafe(
                                    _save_fs(current_agent_id, content, final_answer),
                                    loop
                                ).result(timeout=10)
                            except Exception:
                                pass
                    asyncio.run_coroutine_threadsafe(
                        send({"type": "done"}), loop
                    ).result(timeout=5)

            thread = threading.Thread(target=run_oi, daemon=True)
            thread.start()

    except WebSocketDisconnect:
        log.info("WS disconnected")
    except Exception as e:
        log.error(f"WS error: {e}")
    finally:
        _active_interpreters.pop(ws_id, None)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("DIALEKT_PORT", "8765"))
    host = os.environ.get("DIALEKT_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")
