"""Role-Based Access Control middleware (FastAPI dependencies).

Implements the contract documented in design.md §1.6:

| Token state                              | Result |
|------------------------------------------|--------|
| Missing on protected endpoint            | 401    |
| Malformed/expired on protected endpoint  | 401    |
| Student role on admin endpoint           | 403    |
| Student requesting another student's data| 403    |
| Admin role on admin endpoint             | proceed|
| Student role on student endpoint         | proceed|

The Session_Token is read from the ``httpOnly`` cookie named
:data:`smartkcet.auth.routes.SESSION_COOKIE_NAME` (``smartkcet_session``).
Decoding and revocation checks delegate to
:func:`smartkcet.auth.tokens.validate_token`, which raises
:class:`TokenError` on any failure (missing signature, malformed payload,
expired ``exp``, or revoked ``jti``).

Public surface
--------------

``require_authenticated``
    FastAPI dependency. Returns the decoded JWT payload dict
    (``{sub, role, iat, exp, jti}``).  Raises ``HTTPException(401)`` when
    the cookie is missing or the token fails validation.

``require_student``
    FastAPI dependency.  Builds on ``require_authenticated`` and adds a
    role guard: raises ``HTTPException(403)`` when ``role != 'student'``.

``require_admin``
    FastAPI dependency.  Builds on ``require_authenticated`` and adds a
    role guard: raises ``HTTPException(403)`` when ``role != 'admin'``.

``current_user_id(request)``
    Best-effort helper that returns the ``sub`` claim from the cookie
    token (the KCET_Student_ID for students, the admin email for admins)
    or ``None`` when no valid token is present.  Intended for
    data-scoping queries (e.g. "submissions for *this* student").
    Does **not** raise — callers that need enforcement should depend on
    ``require_student`` / ``require_admin`` separately.

``current_user(request, session)``
    Best-effort helper that resolves the cookie token to the matching
    :class:`User` ORM row, or ``None`` when the token is absent /
    invalid / does not point at a known user.  Used by endpoints that
    need the full user record (display name, email, etc.).

``resolve_payload(request, session)``
    Best-effort helper used by HTML route handlers (task 3.5) to decide
    whether to render the page or issue a ``RedirectResponse``.
    Returns the decoded payload or ``None``; never raises.

JSON vs HTML routes
-------------------

These dependencies always raise ``HTTPException`` (401/403) — they are
the primary surface for the ``/api/*`` JSON routes.  HTML/browser
routes (task 3.5) inspect the cookie via :func:`resolve_payload` and
issue a ``RedirectResponse`` to ``/login`` (unauthenticated) or to the
role-appropriate home (``/dashboard`` / ``/admin``) on role mismatch.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.routes import SESSION_COOKIE_NAME
from ..auth.tokens import TokenError, validate_token
from ..db.models import User
from ..db.session import get_session


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_token(request: Request) -> Optional[str]:
    """Return the raw Session_Token from the cookie, or ``None``."""

    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not isinstance(raw, str) or not raw:
        return None
    return raw


def _unauthorized() -> HTTPException:
    """401 used for missing/malformed/expired tokens on protected endpoints."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "auth_required", "message": "Authentication required."},
    )


def _forbidden() -> HTTPException:
    """403 used for role mismatch and cross-student data access."""

    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "forbidden", "message": "Access denied."},
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies — primary surface for /api/* routes
# ---------------------------------------------------------------------------


def require_authenticated(
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Require any authenticated user.

    Raises
    ------
    HTTPException
        401 when the Session_Token cookie is missing, malformed,
        expired, or has been revoked (REQ-4.2, REQ-4.6).
    """

    raw = _read_token(request)
    if raw is None:
        raise _unauthorized()
    try:
        payload = validate_token(session, raw)
    except TokenError as exc:
        # Don't leak the specific reason (missing / expired / revoked) —
        # the client doesn't need to distinguish.
        raise _unauthorized() from exc
    return payload


def require_student(
    payload: dict[str, Any] = Depends(require_authenticated),
) -> dict[str, Any]:
    """Require a student-role Session_Token.

    Raises
    ------
    HTTPException
        401 — propagated from :func:`require_authenticated`.
        403 when the token authenticates a non-student role (REQ-4.3 in
        reverse: keeps admin tokens off student data-scoping endpoints
        that rely on ``KCET_Student_ID``).
    """

    if payload.get("role") != "student":
        raise _forbidden()
    return payload


def require_admin(
    payload: dict[str, Any] = Depends(require_authenticated),
) -> dict[str, Any]:
    """Require an admin-role Session_Token.

    Raises
    ------
    HTTPException
        401 — propagated from :func:`require_authenticated`.
        403 when the token's role is not ``"admin"`` (REQ-4.3).  No
        response body data beyond the generic "forbidden" envelope is
        returned, as required by the design truth table.
    """

    if payload.get("role") != "admin":
        raise _forbidden()
    return payload


# ---------------------------------------------------------------------------
# Best-effort helpers — never raise
# ---------------------------------------------------------------------------


def resolve_payload(
    request: Request, session: Session
) -> Optional[dict[str, Any]]:
    """Return the decoded JWT payload, or ``None`` on any failure.

    HTML route handlers (task 3.5) call this to choose between rendering
    the page and issuing a ``RedirectResponse``.  Never raises.
    """

    raw = _read_token(request)
    if raw is None:
        return None
    try:
        return validate_token(session, raw)
    except TokenError:
        return None


def current_user_id(request: Request) -> Optional[str]:
    """Return the ``sub`` claim from the cookie token, or ``None``.

    For student tokens this is the ``KCET_Student_ID`` and is the value
    that data-scoping queries should filter ``submissions.user_id`` /
    similar columns by.  For admin tokens this is the configured admin
    email.

    This helper does **not** consult the revocation table — it is a
    convenience for endpoints that have already passed through one of
    the ``require_*`` dependencies (which performs the revocation
    check).  Standalone callers that need enforcement should use the
    dependencies instead.
    """

    raw = _read_token(request)
    if raw is None:
        return None
    # Decode without revocation check — callers that need enforcement
    # are expected to depend on require_authenticated, which already
    # validates revocation.  Decoding still verifies signature + exp.
    try:
        from ..auth.tokens import decode_token  # local import keeps module load light

        payload = decode_token(raw)
    except TokenError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def current_user(request: Request, session: Session) -> Optional[User]:
    """Resolve the cookie token to a :class:`User` ORM row, or ``None``.

    The lookup column depends on role:

    * ``role == 'student'`` → ``users.kcet_student_id == sub``
    * ``role == 'admin'``   → ``users.email == sub``

    Returns ``None`` when the token is absent, invalid, revoked, or
    points at a user that no longer exists.
    """

    payload = resolve_payload(request, session)
    if payload is None:
        return None
    sub = payload.get("sub")
    role = payload.get("role")
    if not isinstance(sub, str) or not sub:
        return None

    if role == "student":
        stmt = select(User).where(User.kcet_student_id == sub)
    elif role == "admin":
        stmt = select(User).where(User.email == sub)
    else:
        return None

    return session.execute(stmt).scalar_one_or_none()


__all__ = [
    "require_authenticated",
    "require_student",
    "require_admin",
    "resolve_payload",
    "current_user_id",
    "current_user",
]
