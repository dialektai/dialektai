"""End-to-end test: dialekt desktop → relay subprocess → live Ollama.

Auto-skipped unless **both** of these are true at module-import time:

  - Ollama reachable at localhost:11434 with the small test model
    pulled (default ``qwen2.5:0.5b``; override with the
    ``DIALEKT_RELAY_E2E_MODEL`` env var).
  - dialekt-cloud test PG reachable. DSN comes from
    ``DIALEKT_CLOUD_TEST_DSN``; defaults to the dialekt-cloud
    convention (``postgresql://dialekt_cloud:dialekt_cloud_pass@
    localhost:5433/dialekt_cloud_test``).

What it covers (the things mocks don't):

  1. ``python -m dialekt.relay`` actually boots and serves on the
     configured port (read from a config-file path, not just code).
  2. asyncpg pool to dialekt_cloud actually connects and the auth
     SELECT against ``relay_keys`` finds a real row.
  3. A real Ollama generation flows through the streaming proxy.
  4. The terminal NDJSON chunk's prompt_eval_count + eval_count are
     captured into a ``relay_usage`` row by the streaming generator's
     finally block.
  5. ``relay_keys.last_used_at`` is bumped in the same transaction.

These are exactly the integrations the unit tests can't reach: the
subprocess boundary, the live PG, and the real Ollama. Token counts
will vary by model and prompt — the test asserts they're positive,
not their exact value.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from dialekt.relay.auth import hash_key  # noqa: E402

OLLAMA_URL = os.environ.get("DIALEKT_RELAY_E2E_OLLAMA", "http://localhost:11434")
DEFAULT_DSN = os.environ.get(
    "DIALEKT_CLOUD_TEST_DSN",
    "postgresql://dialekt_cloud:dialekt_cloud_pass@localhost:5433/dialekt_cloud_test",
)
SMALL_MODEL = os.environ.get("DIALEKT_RELAY_E2E_MODEL", "qwen2.5:0.5b")


# ── reachability probes (run at module import) ─────────────────────────────


def _ollama_reachable() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def _model_pulled(model: str) -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        if r.status_code != 200:
            return False
        names = {m.get("name", "") for m in r.json().get("models", [])}
        if model in names:
            return True
        head = model.split(":")[0]
        return any(n.split(":")[0] == head for n in names)
    except Exception:
        return False


def _pg_reachable(dsn: str) -> bool:
    try:
        import asyncpg

        async def _check():
            conn = await asyncpg.connect(dsn, timeout=3)
            await conn.close()

        asyncio.run(_check())
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_reachable(),
    reason=f"Ollama not reachable at {OLLAMA_URL}",
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def relay_subprocess(*, port: int, dsn: str):
    """Spawn ``python -m dialekt.relay`` on the given port + DSN.

    Yields the relay's base URL once /relay/health responds 200.
    Tears the subprocess down on exit.
    """
    env = dict(os.environ)
    env["DIALEKT_RELAY_PORT"] = str(port)
    env["DIALEKT_RELAY_OLLAMA_URL"] = OLLAMA_URL
    env["DIALEKT_RELAY_DB_URL"] = dsn
    env["DIALEKT_RELAY_LOG_LEVEL"] = "WARNING"
    # Ensure the subprocess can import dialekt.relay even if PYTHONPATH
    # isn't picking up the in-tree package — point cwd at python/.
    proc = subprocess.Popen(
        [sys.executable, "-m", "dialekt.relay"],
        env=env,
        cwd=str(REPO_ROOT / "python"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20.0
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=2)
            raise RuntimeError(
                f"relay process exited early with code {proc.returncode}\n"
                f"stderr: {err.decode()[:1000]}"
            )
        try:
            r = httpx.get(f"{base_url}/relay/health", timeout=1.5)
            if r.status_code == 200:
                break
        except Exception as e:
            last_err = e
            time.sleep(0.4)
    else:
        proc.terminate()
        out, err = proc.communicate(timeout=3)
        raise RuntimeError(
            f"relay didn't come up on :{port} within 20s — last error: {last_err}\n"
            f"stderr: {err.decode()[:1000]}"
        )

    try:
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()


def _seed_tenant_and_key(dsn: str) -> dict:
    """Apply schema (idempotent) and seed one fresh tenant + relay key.

    Returns ``{plaintext, tenant_id, key_id}``.
    """
    import asyncpg
    sys.path.insert(0, str(REPO_ROOT / "dialekt-cloud" / "src"))
    from dialekt_cloud.db import migrate

    plaintext = "dlk_relay_e2e_" + uuid.uuid4().hex
    key_hash = hash_key(plaintext)

    async def _setup():
        pool = await asyncpg.create_pool(dsn)
        try:
            await migrate(pool)
            async with pool.acquire() as conn:
                tid = await conn.fetchval(
                    """
                    INSERT INTO tenants (name, company_name, admin_email, plan)
                    VALUES ('e2e', 'E2E Test', $1, 'team')
                    RETURNING id
                    """,
                    f"e2e-{uuid.uuid4().hex[:8]}@test.local",
                )
                kid = await conn.fetchval(
                    """
                    INSERT INTO relay_keys (tenant_id, name, key_hash)
                    VALUES ($1, 'e2e', $2)
                    RETURNING id
                    """,
                    tid, key_hash,
                )
                return {"tenant_id": str(tid), "key_id": str(kid)}
        finally:
            await pool.close()

    seeded = asyncio.run(_setup())
    return {"plaintext": plaintext, **seeded}


def _read_back(dsn: str, key_id: str) -> tuple:
    """Pull the most recent relay_usage row + the key's last_used_at."""
    import asyncpg

    async def _check():
        pool = await asyncpg.create_pool(dsn)
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT model, prompt_tokens, completion_tokens, latency_ms
                    FROM relay_usage
                    WHERE relay_key_id = $1
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    uuid.UUID(key_id),
                )
                last = await conn.fetchval(
                    "SELECT last_used_at FROM relay_keys WHERE id = $1",
                    uuid.UUID(key_id),
                )
                return row, last
        finally:
            await pool.close()

    return asyncio.run(_check())


# ── the actual test ────────────────────────────────────────────────────────


def test_e2e_generate_records_usage_row():
    if not _model_pulled(SMALL_MODEL):
        pytest.skip(
            f"model {SMALL_MODEL!r} not pulled — set "
            "DIALEKT_RELAY_E2E_MODEL or run `ollama pull qwen2.5:0.5b`"
        )
    if not _pg_reachable(DEFAULT_DSN):
        pytest.skip(f"PG not reachable at {DEFAULT_DSN}")

    seed = _seed_tenant_and_key(DEFAULT_DSN)
    port = _free_port()

    with relay_subprocess(port=port, dsn=DEFAULT_DSN) as base_url:
        r = httpx.post(
            f"{base_url}/relay/generate",
            headers={"Authorization": f"Bearer {seed['plaintext']}"},
            json={
                "model": SMALL_MODEL,
                "prompt": "Reply with the single word: ok",
                "stream": False,
            },
            timeout=120.0,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Ollama's non-streaming /api/generate returns one object with done:true
        assert body.get("done") is True
        # The relay's billing path captured these from the same chunk.
        assert int(body.get("prompt_eval_count", 0)) > 0
        assert int(body.get("eval_count", 0)) >= 1

    # Brief settle so the streaming generator's finally block can flush
    # the INSERT before we read it back.
    time.sleep(0.3)
    row, last_used = _read_back(DEFAULT_DSN, seed["key_id"])

    assert row is not None, "no relay_usage row written for this key"
    assert row["model"]
    assert row["prompt_tokens"] > 0
    assert row["completion_tokens"] >= 1
    assert row["latency_ms"] >= 0
    assert last_used is not None, "relay_keys.last_used_at not bumped"


def test_e2e_unauthenticated_returns_401():
    """The relay rejects unauth'd traffic at the network layer — proves
    the auth dep is wired into the live process, not just unit tests."""
    if not _pg_reachable(DEFAULT_DSN):
        pytest.skip(f"PG not reachable at {DEFAULT_DSN}")

    port = _free_port()
    with relay_subprocess(port=port, dsn=DEFAULT_DSN) as base_url:
        # Health works without auth.
        h = httpx.get(f"{base_url}/relay/health", timeout=2.0)
        assert h.status_code == 200

        # Models requires auth — wrong key should be 401.
        r = httpx.get(
            f"{base_url}/relay/models",
            headers={"Authorization": "Bearer dlk_relay_definitely-not-real"},
            timeout=2.0,
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "auth"
