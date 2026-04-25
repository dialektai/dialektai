"""Founder admin panel — server-rendered HTML at /admin/ui.

Per admin_2fa_DESIGN: the dashboard NEVER receives the admin key in its
HTML context. All authenticated API calls from the dashboard rely on the
httpOnly `dialekt_admin_session` cookie minted only after email + password
+ TOTP via /admin/login flow.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..services.tokens import verify_admin_session_token

router = APIRouter(prefix="/admin/ui", tags=["admin-ui"], include_in_schema=False)
logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "admin"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SESSION_COOKIE = "dialekt_admin_session"


def _get_session(request: Request) -> str | None:
    """Returns the cookie token if it verifies (any logged-in admin).
    Multi-admin ready: payload includes admin_id + email; verifier no
    longer takes the static DIALEKT_ADMIN_KEY as signing material."""
    token = request.cookies.get(SESSION_COOKIE)
    if token and verify_admin_session_token(token, settings.JWT_SECRET):
        return token
    return None


def _require_session(request: Request) -> str:
    token = _get_session(request)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/admin/ui/login"})
    return token


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Pure HTML shell. Login flow is handled client-side against the
    JSON `/admin/login` + `/admin/login/totp` endpoints (which set the
    session cookie themselves on success)."""
    return templates.TemplateResponse(request, "login.html")


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/admin/ui/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _=Depends(_require_session)):
    # Mentor P0: do NOT pass admin_key into the template. Cookie is the
    # only credential the dashboard JS needs; fetch() includes it
    # automatically on same-origin calls.
    return templates.TemplateResponse(request, "dashboard.html", {
        "api_base": "",  # same origin
    })
