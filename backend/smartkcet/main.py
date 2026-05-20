"""FastAPI application factory.

Importing this module yields a configured :data:`app` object that mirrors
the legacy ``backend/app.py`` runtime, plus the new role-scoped routers
introduced by the SmartKCET upgrade.

REQ-3.5 startup config guard
----------------------------

The guard runs at module-import time, **before** ``app = FastAPI(...)``
is constructed and before any route is registered.  On a missing or
malformed admin/JWT/database configuration the guard logs a fatal error
and calls ``sys.exit(1)`` — Uvicorn never starts and the process exits
non-zero.  In production this means importing this module itself fails
fast.  Tests bypass the guard by setting
``SMARTKCET_SKIP_STARTUP_GUARD=1`` in the environment.

Router layout (task 3.5)
------------------------

* ``/api/auth/*``     — :mod:`smartkcet.auth.routes`
* ``/api/admin/*``    — :mod:`smartkcet.admin` (placeholder; admin RBAC)
* ``/api/student/*``  — :mod:`smartkcet.student` (placeholder; student RBAC)
* ``/api/health``     — public health probe defined in this module
* ``/dashboard``,
  ``/admin``,
  ``/admin/{path}``   — :mod:`smartkcet.routes.pages` (HTML redirects)
* ``/upload``,
  ``/generate``,
  ``/analyze``,
  ``/health``, ...    — :mod:`smartkcet.routes.legacy` (kept during the
                         refactor; renaming lands in tasks 4.x and 8.x)
"""

from __future__ import annotations

import warnings
from pathlib import Path

import nest_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Match the noise-suppression done by the legacy entry point.
warnings.filterwarnings("ignore", category=FutureWarning)
nest_asyncio.apply()

# Run the startup config guard FIRST.  On invalid configuration this
# call invokes ``sys.exit(1)`` and the rest of this module never
# executes — Uvicorn therefore never binds a port and the FastAPI
# ``app`` symbol is never exposed.  On success the validated
# :class:`StartupConfig` is cached for subsequent lookups.
from .config import validate_startup_config  # noqa: E402

STARTUP_CONFIG = validate_startup_config()

# Validate Groq API key at startup (non-fatal — logs a warning if invalid
# so the server still starts for non-generation features).
try:
    from .rag.groq_client import validate_groq_api_key, reset_groq_client
    reset_groq_client()  # Force fresh client on every server start
    validate_groq_api_key()
except Exception as _groq_err:
    import logging as _logging
    _logging.getLogger("smartkcet.main").warning(
        "Groq API key validation failed at startup: %s. "
        "The /api/admin/generate endpoint will not work until this is fixed.",
        _groq_err,
    )

from .admin import router as admin_api_router  # noqa: E402
from .auth import router as auth_router  # noqa: E402
from .routes.legacy import router as legacy_router  # noqa: E402
from .routes.pages import router as pages_router  # noqa: E402
from .student import router as student_api_router  # noqa: E402

app = FastAPI(title="ExamForge Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
def api_health() -> dict[str, str]:
    """Public health probe.  REQ-13/14 — used by uptime checks; no auth."""

    return {"status": "ok"}


# Auth_Service routes (task 2.x) under ``/api/auth``.
app.include_router(auth_router)

# Role-scoped API routers (task 3.5) — currently placeholders that future
# tasks (6.x, 7.x, 8.x, 10.x, 11.x) extend.  RBAC is enforced per-endpoint
# via ``Depends(require_admin)`` / ``Depends(require_student)`` inside
# the routers themselves so a public endpoint can be added later without
# tearing down a router-wide dependency.
app.include_router(admin_api_router)
app.include_router(student_api_router)

# HTML pages with role-aware redirects (REQ-3.3, REQ-3.4, REQ-4.7).
app.include_router(pages_router)

# Legacy ExamForge endpoints kept at their original paths for backward
# compat during the refactor.  Renaming (``/api/admin/upload``,
# ``/api/admin/generate``, ``/api/student/submit``) lands in tasks 4.x
# and 8.x.
app.include_router(legacy_router)

# ---------------------------------------------------------------------------
# Static file serving for frontend CSS and JS assets.
# Mounted AFTER routers so explicit route handlers take priority.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"

# /css/* → frontend/css/
if (_FRONTEND_DIR / "css").is_dir():
    app.mount("/css", StaticFiles(directory=str(_FRONTEND_DIR / "css")), name="css")

# /js/* → frontend/js/
if (_FRONTEND_DIR / "js").is_dir():
    app.mount("/js", StaticFiles(directory=str(_FRONTEND_DIR / "js")), name="js")


__all__ = ["app", "STARTUP_CONFIG"]
