from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select

from apps.shared import kpi
from apps.shared.config import settings
from apps.shared.db import session_scope
from apps.shared.enums import UserState
from apps.shared.models import Listing, ScrapeRunHealth, User

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


@router.get("/users", response_class=HTMLResponse)
def page_users(request: Request, _: None = Depends(require_admin)) -> HTMLResponse:
    with session_scope() as s:
        users = s.execute(
            select(User).order_by(desc(User.created_at)).limit(200)
        ).scalars().all()
    return templates.TemplateResponse(
        "admin_users.html", {"request": request, "users": users}
    )


@router.post("/users/{tg_user_id}/pause")
def action_pause(tg_user_id: int, _: None = Depends(require_admin)) -> RedirectResponse:
    with session_scope() as s:
        user = s.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        ).scalar_one_or_none()
        if user:
            user.state = UserState.PAUSED
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{tg_user_id}/resume")
def action_resume(tg_user_id: int, _: None = Depends(require_admin)) -> RedirectResponse:
    with session_scope() as s:
        user = s.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        ).scalar_one_or_none()
        if user:
            user.state = UserState.ACTIVE
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{tg_user_id}/delete")
def action_delete(tg_user_id: int, _: None = Depends(require_admin)) -> RedirectResponse:
    with session_scope() as s:
        user = s.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        ).scalar_one_or_none()
        if user:
            user.state = UserState.DELETED
    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/listings", response_class=HTMLResponse)
def page_listings(
    request: Request,
    state: str = Query(default=""),
    _: None = Depends(require_admin),
) -> HTMLResponse:
    with session_scope() as s:
        q = select(Listing).order_by(desc(Listing.created_at)).limit(100)
        if state:
            q = q.where(Listing.state == state)
        listings = s.execute(q).scalars().all()
    return templates.TemplateResponse(
        "admin_listings.html",
        {"request": request, "listings": listings, "state_filter": state},
    )


@router.post("/listings/{listing_id}/suppress")
def action_suppress(listing_id: int, _: None = Depends(require_admin)) -> RedirectResponse:
    with session_scope() as s:
        listing = s.execute(
            select(Listing).where(Listing.id == listing_id)
        ).scalar_one_or_none()
        if listing:
            listing.suppressed = not listing.suppressed
    return RedirectResponse(url="/admin/listings", status_code=303)


@router.get("/scrape", response_class=HTMLResponse)
def page_scrape(request: Request, _: None = Depends(require_admin)) -> HTMLResponse:
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    with session_scope() as s:
        rows = s.execute(
            select(
                ScrapeRunHealth.category,
                func.sum(ScrapeRunHealth.success_count).label("success"),
                func.sum(ScrapeRunHealth.failure_count).label("failure"),
                func.bool_or(ScrapeRunHealth.used_playwright_fallback).label("playwright"),
            )
            .where(ScrapeRunHealth.ts >= cutoff)
            .group_by(ScrapeRunHealth.category)
            .order_by(ScrapeRunHealth.category)
        ).all()
    health = [
        {
            "category": r.category,
            "success": r.success or 0,
            "failure": r.failure or 0,
            "rate": (r.success or 0) / ((r.success or 0) + (r.failure or 0))
                    if ((r.success or 0) + (r.failure or 0)) > 0 else 0.0,
            "playwright": r.playwright,
        }
        for r in rows
    ]
    return templates.TemplateResponse(
        "admin_scrape.html", {"request": request, "health": health}
    )
