from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from apps.shared import kpi
from apps.shared.config import settings
from apps.shared.db import session_scope
from apps.shared.enums import ListingState, UserState
from apps.shared.models import Listing, ScrapeRunHealth, User
from sqlalchemy import desc, func, select

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def require_admin(admin_session: str = Cookie(default="")) -> None:
    if not settings.admin_token or admin_session != settings.admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/login")
def admin_login(token: str = Query(default="")) -> RedirectResponse:
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")
    resp = RedirectResponse(url="/admin", status_code=302)
    resp.set_cookie("admin_session", token, httponly=True, samesite="strict")
    return resp


@router.get("", response_class=HTMLResponse)
def page_kpi(request: Request, _: None = Depends(require_admin)) -> HTMLResponse:
    with session_scope() as s:
        ctx = {
            "like_rate": kpi.like_rate(s),
            "contact_rate": kpi.contact_rate(s),
            "mute_rate": kpi.mute_rate(s),
            "days_to_success": kpi.days_to_success(s),
        }
    return templates.TemplateResponse("admin_kpi.html", {"request": request, **ctx})
