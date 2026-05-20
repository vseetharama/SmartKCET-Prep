"""HTML page routes with role-aware redirects and static file serving.

This router serves all frontend HTML pages and implements the routing
truth table from design.md:

| Path             | Auth state          | Response                    |
|------------------|---------------------|-----------------------------|
| ``/``            | unauthenticated     | serve landing.html          |
| ``/``            | student             | 302 → /dashboard           |
| ``/``            | admin               | 302 → /admin/upload        |
| ``/index.html``  | (same as ``/``)     | (same as ``/``)            |
| ``/login``       | any                 | serve login.html            |
| ``/register``    | any                 | serve register.html         |
| ``/dashboard``   | unauthenticated     | 302 → /login               |
| ``/dashboard``   | admin               | 302 → /admin/upload        |
| ``/dashboard``   | student             | serve dashboard.html        |
| ``/exam``        | unauthenticated     | 302 → /login               |
| ``/exam``        | student             | serve exam.html             |
| ``/admin/upload``| unauthenticated     | 302 → /login               |
| ``/admin/upload``| student             | 302 → /dashboard           |
| ``/admin/upload``| admin               | serve admin-upload.html     |
| ``/admin/*``     | (same pattern)      | (same pattern)              |

Static assets (``/css/*``, ``/js/*``) are served via FastAPI's
``StaticFiles`` mount configured in ``main.py``.

Requirements: 13.5, 13.6
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..middleware.rbac import resolve_payload

router = APIRouter(tags=["pages"])

# Resolve the frontend/html directory relative to this file.
# Structure: backend/smartkcet/routes/pages.py → ../../.. → project root → frontend/html
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_HTML_DIR = _PROJECT_ROOT / "frontend" / "html"

# Standard redirect status for browser navigation (302 Found).
_REDIRECT_STATUS = status.HTTP_302_FOUND


# ---------------------------------------------------------------------------
# Admin sub-page mapping
# ---------------------------------------------------------------------------

_ADMIN_PAGES = {
    "upload": "admin-upload.html",
    "questions": "admin-questions.html",
    "exams": "admin-exams.html",
    "analytics": "admin-analytics.html",
}


# ---------------------------------------------------------------------------
# Root path: / and /index.html
# ---------------------------------------------------------------------------


@router.get("/", response_model=None)
@router.get("/index.html", response_model=None)
def root_page(
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse | RedirectResponse:
    """Root path with role-aware redirects (REQ-13.5, REQ-13.6).

    - Unauthenticated → serve landing.html
    - Authenticated student → 302 to /dashboard
    - Authenticated admin → 302 to /admin/upload
    """
    payload = resolve_payload(request, session)
    if payload is None:
        return FileResponse(str(_HTML_DIR / "landing.html"), media_type="text/html")

    role = payload.get("role")
    if role == "student":
        return RedirectResponse(url="/dashboard", status_code=_REDIRECT_STATUS)
    if role == "admin":
        return RedirectResponse(url="/admin/upload", status_code=_REDIRECT_STATUS)

    # Unknown role — treat as unauthenticated.
    return FileResponse(str(_HTML_DIR / "landing.html"), media_type="text/html")


# ---------------------------------------------------------------------------
# Public pages (no auth required)
# ---------------------------------------------------------------------------


@router.get("/login", response_model=None)
def login_page() -> FileResponse:
    """Serve the login page."""
    return FileResponse(str(_HTML_DIR / "login.html"), media_type="text/html")


@router.get("/register", response_model=None)
def register_page() -> FileResponse:
    """Serve the registration page."""
    return FileResponse(str(_HTML_DIR / "register.html"), media_type="text/html")


# ---------------------------------------------------------------------------
# Student pages (auth required)
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=None)
def dashboard_page(
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse | RedirectResponse:
    """Student dashboard with role-aware redirects."""
    payload = resolve_payload(request, session)
    if payload is None:
        return RedirectResponse(url="/login", status_code=_REDIRECT_STATUS)

    role = payload.get("role")
    if role == "admin":
        return RedirectResponse(url="/admin/upload", status_code=_REDIRECT_STATUS)
    if role == "student":
        return FileResponse(str(_HTML_DIR / "dashboard.html"), media_type="text/html")

    # Unknown role — redirect to login.
    return RedirectResponse(url="/login", status_code=_REDIRECT_STATUS)


@router.get("/exam", response_model=None)
def exam_page(
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse | RedirectResponse:
    """Exam page — student only."""
    payload = resolve_payload(request, session)
    if payload is None:
        return RedirectResponse(url="/login", status_code=_REDIRECT_STATUS)

    role = payload.get("role")
    if role == "student":
        return FileResponse(str(_HTML_DIR / "exam.html"), media_type="text/html")
    if role == "admin":
        return RedirectResponse(url="/admin/upload", status_code=_REDIRECT_STATUS)

    return RedirectResponse(url="/login", status_code=_REDIRECT_STATUS)


# ---------------------------------------------------------------------------
# Admin pages (admin auth required)
# ---------------------------------------------------------------------------


def _admin_page_response(
    request: Request, session: Session, html_file: str
) -> FileResponse | RedirectResponse:
    """Shared handler for admin sub-pages."""
    payload = resolve_payload(request, session)
    if payload is None:
        return RedirectResponse(url="/login", status_code=_REDIRECT_STATUS)

    role = payload.get("role")
    if role == "student":
        return RedirectResponse(url="/dashboard", status_code=_REDIRECT_STATUS)
    if role == "admin":
        return FileResponse(str(_HTML_DIR / html_file), media_type="text/html")

    return RedirectResponse(url="/login", status_code=_REDIRECT_STATUS)


@router.get("/admin/upload", response_model=None)
def admin_upload_page(
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse | RedirectResponse:
    """Admin upload/generator page (historical index.html generator UI)."""
    return _admin_page_response(request, session, "admin-upload.html")


@router.get("/admin/questions", response_model=None)
def admin_questions_page(
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse | RedirectResponse:
    """Admin question bank management page."""
    return _admin_page_response(request, session, "admin-questions.html")


@router.get("/admin/exams", response_model=None)
def admin_exams_page(
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse | RedirectResponse:
    """Admin exam creation and publish page."""
    return _admin_page_response(request, session, "admin-exams.html")


@router.get("/admin/analytics", response_model=None)
def admin_analytics_page(
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse | RedirectResponse:
    """Admin analytics page."""
    return _admin_page_response(request, session, "admin-analytics.html")


@router.get("/admin", response_model=None)
def admin_root_page(
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse | RedirectResponse:
    """Admin panel root — redirects to /admin/upload for admin users."""
    payload = resolve_payload(request, session)
    if payload is None:
        return RedirectResponse(url="/login", status_code=_REDIRECT_STATUS)

    role = payload.get("role")
    if role == "student":
        return RedirectResponse(url="/dashboard", status_code=_REDIRECT_STATUS)
    if role == "admin":
        # Admin root redirects to the upload page (the primary admin landing).
        return RedirectResponse(url="/admin/upload", status_code=_REDIRECT_STATUS)

    return RedirectResponse(url="/login", status_code=_REDIRECT_STATUS)


__all__ = ["router"]
