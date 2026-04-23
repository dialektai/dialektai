"""Founder admin panel — server-rendered HTML at /admin/ui."""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..services.tokens import create_admin_session_token, verify_admin_session_token

router = APIRouter(prefix="/admin/ui", tags=["admin-ui"], include_in_schema=False)
logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "admin"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SESSION_COOKIE = "dialekt_admin_session"


def _get_session(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if token and verify_admin_session_token(token, settings.DIALEKT_ADMIN_KEY, settings.JWT_SECRET):
        return token
    return None


def _require_session(request: Request) -> str:
    token = _get_session(request)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/admin/ui/login"})
    return token


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    key = form.get("admin_key", "")
    if key != settings.DIALEKT_ADMIN_KEY:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Неверный ключ доступа"}
        )
    token = create_admin_session_token(settings.DIALEKT_ADMIN_KEY, settings.JWT_SECRET)
    resp = RedirectResponse("/admin/ui/", status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, secure=False, samesite="lax", max_age=3600)
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/admin/ui/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _=Depends(_require_session)):
    return templates.TemplateResponse(request, "dashboard.html", {
        "admin_key": settings.DIALEKT_ADMIN_KEY,
        "api_base": "",  # same origin
    })
