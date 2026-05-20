"""HTTP endpoints for the Auth_Service.

Mounted under ``/api/auth`` from :mod:`smartkcet.main`:

* ``POST /api/auth/register``     — REQ-1.x, registration with pre-hash
                                     duplicate-email check.
* ``POST /api/auth/login``        — REQ-2.x, student login with lockout.
* ``POST /api/auth/admin/login``  — REQ-3.x, admin login with the
                                     no-token-on-failure guarantee.
* ``POST /api/auth/logout``       — REQ-2.7, jti-revocation logout.

The endpoints are deliberately kept compact so the duplicate-email-before-
hashing ordering (REQ-1.2 / Property 2) and the single ``issue_token(...)``
call site for admin login (REQ-3.2 / Property 7) are obvious from a
straight read of the file.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..db.models import User
from ..db.session import get_session
from .admin_config import load_admin_credentials
from .identity import next_kcet_id
from .passwords import hash_password, verify_password
from .tokens import (
    ADMIN_TOKEN_TTL_SEC,
    STUDENT_TOKEN_TTL_SEC,
    TokenError,
    issue_token,
    revoke_token,
    validate_token,
)
from .validation import (
    ValidationFailure,
    validate_display_name,
    validate_email,
    validate_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# Cookie used by the browser session.  REQ-14.5 — token never lives in
# localStorage; ``httpOnly`` keeps it out of JS reach.
SESSION_COOKIE_NAME = "smartkcet_session"

# REQ-2.6 lockout policy.
MAX_FAILED_LOGINS = 5
LOCKOUT_WINDOW = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """UTC ``now``.  ORM columns store naive UTC, so strip tzinfo."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    """Write the Session_Token to an ``httpOnly`` cookie."""

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # production should set secure=True (TLS-only).
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def _validation_error(failure: ValidationFailure) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "validation_error",
            "field": failure.field,
            "message": failure.reason,
        },
    )


# REQ-2.2 / REQ-3.2: byte-identical generic auth failure response.  The
# function returns a fresh dict each time so callers can't mutate the
# canonical body.
def _generic_auth_failure() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"error": "auth_failed", "message": "Invalid credentials"},
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, session: Session = Depends(get_session)) -> Any:
    """Register a new student account.

    Order of operations is mandated by REQ-1.2 and REQ-1.3:

    1. Pure validation (no DB, no hashing).
    2. Duplicate-email ``SELECT`` (DB).
    3. ``hash_password`` (only if step 2 found nothing).
    4. ``INSERT`` user with freshly minted KCET_Student_ID.

    Steps 3 and 4 share a transaction so a crash between them leaves the
    DB clean.  The ``UNIQUE`` constraint on ``users.email`` provides a
    last-line race guard.
    """

    # Step 1 — validation.  No DB / no hashing yet.
    email_v = validate_email(payload.email)
    if isinstance(email_v, ValidationFailure):
        return _validation_error(email_v)

    password_v = validate_password(payload.password)
    if isinstance(password_v, ValidationFailure):
        return _validation_error(password_v)

    name_v = validate_display_name(payload.display_name)
    if isinstance(name_v, ValidationFailure):
        return _validation_error(name_v)

    normalised_email = email_v.lower()

    # Step 2 — duplicate-email pre-check.  Runs BEFORE hash_password.
    existing = session.execute(
        select(User.id).where(User.email == normalised_email)
    ).first()
    if existing is not None:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "email_already_registered",
                "message": "This email is already registered.",
            },
        )

    # Step 3 — hashing.  Reachable only when the email is free.
    password_hash = hash_password(password_v)

    # Step 4 — issue KCET_Student_ID and persist user.
    kcet_id = next_kcet_id(session)
    user = User(
        email=normalised_email,
        kcet_student_id=kcet_id,
        display_name=name_v,
        password_hash=password_hash,
        role="student",
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent register hit the unique constraint after our pre-check.
        session.rollback()
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "email_already_registered",
                "message": "This email is already registered.",
            },
        )

    return {
        "kcet_student_id": kcet_id,
        "email": normalised_email,
        "display_name": name_v,
    }


# ---------------------------------------------------------------------------
# POST /api/auth/login (student)
# ---------------------------------------------------------------------------


def _is_locked(user: User, now: datetime) -> bool:
    return user.lockout_until is not None and user.lockout_until > now


def _record_failed_attempt(user: User, now: datetime) -> None:
    """Increment counter and lock account on the 5th consecutive failure."""

    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= MAX_FAILED_LOGINS:
        user.lockout_until = now + LOCKOUT_WINDOW


def _reset_lockout(user: User) -> None:
    user.failed_login_count = 0
    user.lockout_until = None


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> Any:
    """Student login with lockout policy and generic-failure response.

    Per REQ-2.2 / Property 3 the response for "wrong password" and
    "unregistered email" is byte-identical.  Lockout (REQ-2.6 /
    Property 5) returns a separate 423 response carrying the remaining
    wait time.
    """

    # Lightweight shape check — empty strings short-circuit to the
    # generic auth failure (no DB call needed).
    if not isinstance(payload.email, str) or not payload.email:
        return _generic_auth_failure()
    if not isinstance(payload.password, str) or not payload.password:
        return _generic_auth_failure()

    normalised_email = payload.email.strip().lower()
    now = _now()

    try:
        user = session.execute(
            select(User).where(User.email == normalised_email, User.role == "student")
        ).scalar_one_or_none()
    except OperationalError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "service_unavailable",
                "message": "Database temporarily unavailable. Please try again later.",
            },
        )

    # Unregistered email → identical generic failure (no timing-side-channel
    # work needed for REQ-2.2; full constant-time comparison is out of
    # scope here).
    if user is None:
        return _generic_auth_failure()

    # Locked account → 423, with remaining wait time.
    if _is_locked(user, now):
        retry_after_sec = max(int((user.lockout_until - now).total_seconds()), 1)
        # Failed login while locked does NOT increment the counter
        # (design.md §1.5).
        return JSONResponse(
            status_code=status.HTTP_423_LOCKED,
            content={
                "error": "account_locked",
                "message": "Account temporarily locked. Try again later.",
                "retry_after_sec": retry_after_sec,
            },
            headers={"Retry-After": str(retry_after_sec)},
        )

    # Lockout window may have elapsed since the last attempt — clean up
    # before evaluating the password (design.md §1.5 row 5).
    if user.lockout_until is not None and user.lockout_until <= now:
        _reset_lockout(user)

    if not verify_password(payload.password, user.password_hash):
        _record_failed_attempt(user, now)
        try:
            session.commit()
        except OperationalError:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "service_unavailable",
                    "message": "Database temporarily unavailable. Please try again later.",
                },
            )
        return _generic_auth_failure()

    # Successful login.
    _reset_lockout(user)
    try:
        session.commit()
    except OperationalError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "service_unavailable",
                "message": "Database temporarily unavailable. Please try again later.",
            },
        )

    token, _jti, _iat, _exp = issue_token(sub=user.kcet_student_id, role="student")
    _set_session_cookie(response, token, max_age=STUDENT_TOKEN_TTL_SEC)

    return {
        "kcet_student_id": user.kcet_student_id,
        "display_name": user.display_name,
        "role": "student",
    }


# ---------------------------------------------------------------------------
# POST /api/auth/admin/login
# ---------------------------------------------------------------------------


@router.post("/admin/login")
def admin_login(payload: LoginRequest, response: Response) -> Any:
    """Admin login.  REQ-3.2 / Property 7 — no token of any kind on failure.

    The handler resolves the configured admin credentials, runs a
    constant-time email compare and a bcrypt password verify.  The
    ``issue_token(...)`` call site lives at the bottom of the function
    inside an ``if both_match:`` gate.  There is no fallback path that
    issues *any* token when either field is wrong.
    """

    # Compute "both fields match" up-front so the issuance call is a
    # single boolean check.
    creds = load_admin_credentials()
    email_str = payload.email if isinstance(payload.email, str) else ""
    password_str = payload.password if isinstance(payload.password, str) else ""

    email_match = (
        creds is not None
        and hmac.compare_digest(email_str.strip().lower(), creds.email)
    )
    password_match = (
        creds is not None
        and bool(password_str)
        and verify_password(password_str, creds.password_hash)
    )

    if not (email_match and password_match):
        # No Set-Cookie header is written.  No token is issued.  The
        # response body is identical to the student-login generic failure.
        return _generic_auth_failure()

    # Single issuance site, gated on full credential match.
    token, _jti, _iat, _exp = issue_token(sub=creds.email, role="admin")
    _set_session_cookie(response, token, max_age=ADMIN_TOKEN_TTL_SEC)
    return {"role": "admin", "email": creds.email}


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> Any:
    """Revoke the active Session_Token and clear the cookie."""

    raw = request.cookies.get(SESSION_COOKIE_NAME)
    revoked = False
    if raw:
        try:
            payload = validate_token(session, raw)
        except TokenError:
            payload = None
        if payload:
            jti = payload.get("jti")
            exp_unix = payload.get("exp")
            expires_at: datetime | None = None
            if isinstance(exp_unix, (int, float)):
                expires_at = datetime.fromtimestamp(exp_unix, tz=timezone.utc).replace(
                    tzinfo=None
                )
            if revoke_token(session, jti, expires_at=expires_at):
                session.commit()
                revoked = True

    _clear_session_cookie(response)
    return {"logged_out": True, "revoked": revoked}


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------


@router.get("/me")
def me(
    request: Request,
    session: Session = Depends(get_session),
) -> Any:
    """Return the current user's role and identity.

    Used by the frontend ``auth.js`` module to determine the active
    session without reading the ``httpOnly`` cookie directly.  Returns
    401 when no valid session exists.
    """

    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "not_authenticated", "message": "No active session."},
        )
    try:
        payload = validate_token(session, raw)
    except TokenError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "not_authenticated", "message": "No active session."},
        )

    role = payload.get("role")
    sub = payload.get("sub")

    result: dict[str, Any] = {"authenticated": True, "role": role, "sub": sub}

    # For students, include display name and KCET ID.
    if role == "student":
        user = session.execute(
            select(User).where(User.kcet_student_id == sub)
        ).scalar_one_or_none()
        if user:
            result["display_name"] = user.display_name
            result["kcet_student_id"] = user.kcet_student_id

    return result


__all__ = ["router", "SESSION_COOKIE_NAME"]
