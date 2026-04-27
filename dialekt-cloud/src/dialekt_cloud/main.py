"""dialekt-cloud FastAPI application."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import settings, assert_production_ready
from .db import close_pool, get_pool, migrate
from .routers import admin, admin_ui, agents, auth, health, public
from .services.email import EmailService
from .services.scheduler import run_lifecycle_scheduler

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting dialekt-cloud (env=%s)...", settings.ENV)

    # Production safety: refuse to boot if security-critical knobs are still
    # the dev defaults, or if SMTP credentials are missing. Better to die
    # at startup with a clear list than to run a leaky stack.
    problems = assert_production_ready()
    if problems:
        logger.error("Production-readiness check FAILED:")
        for p in problems:
            logger.error("  - %s", p)
        raise RuntimeError(
            "dialekt-cloud refuses to start in production with %d unresolved issues "
            "(see logs). Set ENV=development if this is a dev box." % len(problems)
        )

    pool = await get_pool(settings.DATABASE_URL)
    app.state.pool = pool
    await migrate(pool)
    # Seed the public library catalog. Idempotent — safe on every boot.
    # Disable in tests via DIALEKT_DISABLE_LIBRARY_SEED.
    if os.environ.get("DIALEKT_DISABLE_LIBRARY_SEED", "").lower() not in ("1", "true", "yes"):
        try:
            from .services.library_seed import seed_library_entries
            await seed_library_entries(pool)
        except Exception as exc:
            logger.warning("library seed skipped: %s", exc)
    app.state.email = EmailService(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        user=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        from_addr=settings.SMTP_FROM,
        use_tls=settings.SMTP_TLS,
    )

    # Soft check on startup: warn (don't crash) if no admin exists yet.
    # Useful for the very first deploy where the operator is about to run
    # `dialekt-admin admin create` but hasn't yet.
    try:
        async with pool.acquire() as conn:
            n_admins = await conn.fetchval("SELECT COUNT(*) FROM admins")
        if n_admins == 0:
            logger.warning(
                "no admins in DB yet — dashboard login will refuse everyone except the "
                "break-glass key. Bootstrap with: dialekt-admin admin create --email=zhumagaliyev@dias.now"
            )
    except Exception as exc:
        logger.warning("admin presence check skipped: %s", exc)
    # Background tasks (trial-expiring reminders etc.) Disable in tests
    # via DIALEKT_DISABLE_SCHEDULER=true so the test suite doesn't spawn
    # a background loop that keeps trying to email mocked tenants.
    scheduler_task: asyncio.Task | None = None
    if os.environ.get("DIALEKT_DISABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
        scheduler_task = asyncio.create_task(run_lifecycle_scheduler(app))
    logger.info("dialekt-cloud ready")
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
        await close_pool()


app = FastAPI(
    title="dialekt-cloud",
    version="0.1.0",
    description="dias.now cloud service — license management and agent registry",
    docs_url="/docs" if settings.ENV != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dias.now", "https://dialekt.dias.now", "tauri://localhost", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(admin.router)
app.include_router(admin_ui.router)
app.include_router(public.router)


# ── Root landing page ────────────────────────────────────────────────────────
# A bare GET / on the cloud-API subdomain used to return {"detail":"Not Found"}.
# Show a small human-readable page that explains what this hostname is and
# points admins at /admin/ui/ + users at the desktop download.

_ROOT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>dialekt-cloud · API</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: 'JetBrains Mono', ui-monospace, monospace;
         background: #0a0d12; color: #e2e8f0; margin: 0;
         min-height: 100vh; display: flex; align-items: center; justify-content: center; }
  .card { max-width: 640px; padding: 40px 44px; background: #0f1318;
          border: 1px solid #1e2733; }
  h1 { font-size: 20px; color: #00d4ff; letter-spacing: 0.08em; margin: 0 0 8px; }
  h2 { font-size: 14px; color: #94a3b8; letter-spacing: 0.1em;
       text-transform: uppercase; margin: 24px 0 8px; font-weight: 500; }
  p  { font-size: 13px; color: #94a3b8; line-height: 1.7; margin: 0 0 12px; }
  a  { color: #00d4ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  code { color: #e2e8f0; background: #0a0d12; padding: 1px 6px;
         border: 1px solid #1e2733; font-size: 12px; }
  ul { margin: 8px 0 0; padding-left: 18px; font-size: 13px;
       color: #94a3b8; line-height: 1.8; }
</style>
</head>
<body>
<div class="card">
  <h1>dialekt-cloud</h1>
  <p>License, invite and agent-registry service for <a href="https://dialekt.dias.now">dias.now</a>.</p>

  <h2>If you're a user</h2>
  <p>Download the desktop app from <a href="https://dialekt.dias.now">dialekt.dias.now</a>.
     This hostname is the backend API — it doesn't render a user-facing UI.</p>

  <h2>If you're the founder / admin</h2>
  <p>Sign in at <a href="/admin/ui/login">/admin/ui/login</a> with your admin key.</p>

  <h2>Machine-readable endpoints</h2>
  <ul>
    <li><code>GET  /health</code> — service status</li>
    <li><code>POST /auth/validate-license</code> — desktop activation</li>
    <li><code>POST /auth/accept-invite</code> — colleague redeem</li>
    <li><code>GET  /agents/assigned-to-me</code> — agent sync (bearer)</li>
    <li><code>GET  /admin/ui/</code> — founder admin panel</li>
  </ul>
</div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    return HTMLResponse(_ROOT_HTML)


@app.get("/admin", include_in_schema=False)
async def admin_redirect():
    # convenience: /admin → /admin/ui/ (people will type the short form)
    return RedirectResponse("/admin/ui/", status_code=307)


@app.get("/releases/latest")
async def releases_latest():
    """Proxy of the latest release feed used by the landing `#download`
    section AND by the in-app updater banner. Centralising the call
    here means dias.now / the app HTML never references the upstream
    source-of-truth URL — that stays hidden in the cloud server.

    Asset URLs in the response still point at the upstream CDN;
    mirroring those onto a dial-now-owned domain is a follow-up.
    """
    from .services.releases import get_latest_releases, releases_summary
    data = await get_latest_releases()
    return {
        "tag": data.get("version", "latest"),
        "published_at": data.get("published_at"),
        # Where to point users for the human-readable release page. We
        # send them back to the landing's own download section instead
        # of the upstream — the landing fetches THIS endpoint to render.
        "url": settings.LANDING_URL.rstrip("/") + "/#download",
        "downloads": releases_summary(data),
    }
