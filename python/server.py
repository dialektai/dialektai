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
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    model        TEXT NOT NULL DEFAULT 'gemma3-12b',
    title        TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
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
"""


async def _init_db():
    await db.executescript(_SCHEMA)
    await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await _init_db()
    log.info(f"SQLite ready at {DB_PATH}")
    yield
    await db.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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

async def db_create_session(model: str = "gemma3-12b") -> str:
    sid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO sessions(id, model) VALUES(?, ?)",
        (sid, model),
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


@app.get("/sessions")
async def list_sessions():
    cursor = await db.execute(
        "SELECT id, title, model, created_at, updated_at, message_count "
        "FROM sessions ORDER BY updated_at DESC LIMIT 50"
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": r["id"],
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


def make_interpreter():
    from interpreter import interpreter
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
                    "SELECT role, content FROM messages WHERE session_id=? AND type='message' ORDER BY created_at",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                itp.messages = [{"role": r["role"], "type": "message", "content": r["content"]} for r in rows]
                await send({"type": "joined", "session_id": session_id})
                continue

            if msg.get("type") != "chat":
                continue

            content = msg.get("content", "").strip()
            if not content:
                continue

            if session_id is None:
                sid_from_client = msg.get("session_id")
                if sid_from_client:
                    session_id = sid_from_client
                else:
                    session_id = await db_create_session()
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
                    if ai_text_buf:
                        asyncio.run_coroutine_threadsafe(
                            db_save_message(session_id, "assistant", "message", "".join(ai_text_buf)),
                            loop
                        ).result(timeout=5)
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
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
