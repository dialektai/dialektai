"""dialekt-cloud FastAPI application."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import close_pool, get_pool, migrate
from .routers import admin, admin_ui, agents, auth, health
from .services.email import EmailService

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting dialekt-cloud...")
    pool = await get_pool(settings.DATABASE_URL)
    app.state.pool = pool
    await migrate(pool)
    app.state.email = EmailService(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        user=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        from_addr=settings.SMTP_FROM,
        use_tls=settings.SMTP_TLS,
    )
    logger.info("dialekt-cloud ready")
    yield
    await close_pool()


app = FastAPI(
    title="dialekt-cloud",
    version="0.1.0",
    description="dialekt.ai cloud service — license management and agent registry",
    docs_url="/docs" if settings.ENV != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dialekt.dias.now", "tauri://localhost", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(admin.router)
app.include_router(admin_ui.router)
