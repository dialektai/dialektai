# Dialekt plugin backend access (`PluginContext`)

**Short version:** dialekt LLM plugins — DialektSQL, the retry loop,
anything you add next — should NOT call `httpx.post("http://localhost:8765/…")`
directly. Go through `dialekt.llm._plugin_context.get_context()` instead.

The context handles two transports transparently:

| Caller is… | Mode | Transport |
|---|---|---|
| running **inside** the dialekt-server process (production, tests) | in-process | persistent anyio portal + `httpx.AsyncClient(ASGITransport(app))` |
| running **outside** the server (detached worker, CLI, third-party script) | http | `httpx.Client(base_url=DIALEKT_BACKEND_URL)` |

## Usage

```python
from dialekt.llm._plugin_context import get_context

def my_plugin_work(conn_id: str):
    ctx = get_context()
    r = ctx.post(
        f"/connections/{conn_id}/query",
        json={"sql": "SELECT 1", "retry": False},
    )
    if r.status_code >= 400:
        raise RuntimeError(r.text)
    return r.json()
```

The interface mirrors `httpx.Client` (`.post`, `.get`, `.delete`,
`.patch`). Responses expose `.status_code`, `.json()`, `.text` — same
as httpx.

If your plugin is **async**, wrap the sync call in `asyncio.to_thread`
(the context API is sync to keep Open Interpreter's language-plugin
integration simple — OI doesn't `await`):

```python
import asyncio
async def validate(conn_id, sql):
    ctx = get_context()
    def _do():
        return ctx.post(f"/connections/{conn_id}/query",
                        json={"sql": sql, "retry": False})
    r = await asyncio.to_thread(_do)
    return r.json()
```

## Installing the context

Production `server.py` does this in its `lifespan` startup:

```python
from dialekt.llm._plugin_context import PluginContext, set_context
set_context(PluginContext(app=app))
```

Tests that need in-process dispatch (all role_user chat tests that
generate SQL, plus future plugin integration tests) do the same:

```python
@pytest.fixture
def client_with_plugin_context():
    import server as srv
    from fastapi.testclient import TestClient
    from dialekt.llm._plugin_context import PluginContext, set_context

    with TestClient(srv.app) as c:
        set_context(PluginContext(app=srv.app))
        yield c
        # Lifespan shutdown resets to default via set_context(None)
```

Tests that need a **stub** context (unit tests for DialektSQL/
retry_loop) inject a fake:

```python
class _FakeCtx:
    def post(self, path, **kw): ...
    def close(self): pass

pc.set_context(_FakeCtx())
```

See `python/tests/test_sql_language.py` for the full pattern — every
DialektSQL test uses `_FakePluginContext` + a `restore_context`
fixture that puts the real one back after each case.

## Why a persistent portal?

The obvious approach would be `TestClient(app)` — one line, easy to
understand. Don't do it.

- `TestClient.post()` spins up a **fresh** anyio portal per request
- each portal creates its own event loop
- asyncpg connection pools (`mcp_servers/postgres_mcp._pools`) are
  bound to the loop they were first touched on
- second query on the same connection → different loop → asyncpg
  raises `another operation is in progress`

`_PersistentASGIClient` (inside `_plugin_context.py`) starts ONE
`anyio.from_thread.start_blocking_portal` at context-init time and
reuses it for every request. The pool's loop stays alive, all SQL
runs on it, no cross-loop pain.

The cost: one extra background thread per `PluginContext` instance.
In practice we only have one context at a time (the module-level
singleton), so it's effectively a no-op.

## Env-var contract

Backward compatibility with the pre-consolidation era (commit
`12d663c` introduced `DIALEKT_BACKEND_URL` for the retry loop; an
earlier `DIALEKT_API` was the DialektSQL variant):

| Env var | Read by | Since | Status |
|---|---|---|---|
| `DIALEKT_BACKEND_URL` | `PluginContext` default for http mode | R1 fix (2026-04-24) | **canonical** |
| `DIALEKT_API` | — no longer read | R1 era | **removed** (grep confirms no callers) |

If you set `DIALEKT_BACKEND_URL`, http-mode contexts pick it up at
`PluginContext()` init time. In-process mode doesn't care — the app
is already in memory.

## Adding a new plugin

1. Import `get_context` from `dialekt.llm._plugin_context`.
2. Call `ctx.post(path, json=…)` or `ctx.get(path, params=…)`.
3. Add a unit test that injects `_FakePluginContext` via `set_context()`
   to capture the request path/body and verify response handling.
4. If your plugin is async, wrap sync calls with `asyncio.to_thread`.
5. Add a test that asserts your plugin survives a real in-process
   dispatch via a TestClient fixture with a live FastAPI app — this
   proves the persistent portal works end-to-end for your use case
   (copy the role_user pattern).

Don't:

- import `httpx` directly and talk to `http://localhost:8765` —
  that breaks under TestClient and under non-default ports
- rely on a specific transport type — today it's persistent portal +
  ASGITransport, tomorrow it could be direct in-process ASGI calls
  skipping httpx entirely. Stick to the `.post`/`.get` interface.
