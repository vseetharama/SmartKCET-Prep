"""Unit tests for root-path routing and page serving (task 16.1).

Validates:
- `/` and `/index.html` serve landing.html for unauthenticated visitors
- Authenticated student GET `/` → 302 to `/dashboard`
- Authenticated admin GET `/` → 302 to `/admin/upload`
- Static page routes serve the correct HTML files
- Admin pages redirect unauthenticated users to /login
- Admin pages redirect students to /dashboard

Requirements: 13.5, 13.6
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Environment setup MUST happen before any smartkcet import.
os.environ.setdefault("SMARTKCET_SKIP_STARTUP_GUARD", "1")
_TMP_DB = Path(tempfile.mkdtemp()) / "test_routing.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DB.as_posix()}")
os.environ.setdefault("JWT_SECRET", "test-routing-secret-1234567890")

import pytest
from fastapi.testclient import TestClient

from smartkcet.auth.routes import SESSION_COOKIE_NAME
from smartkcet.auth.tokens import issue_token
from smartkcet.db.base import Base
from smartkcet.db.session import engine
from smartkcet.main import app


@pytest.fixture(scope="module", autouse=True)
def _create_tables():
    """Create all DB tables before tests run."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def student_token() -> str:
    token, _jti, _iat, _exp = issue_token(
        sub="KCET0001",
        role="student",
        student_subtype="direct_subscriber",
        subscription_status="trial",
    )
    return token


@pytest.fixture()
def admin_token() -> str:
    token, _jti, _iat, _exp = issue_token(sub="admin@test.com", role="platform_admin")
    return token


class TestRootPath:
    """Tests for `/` and `/index.html` routing."""

    def test_unauthenticated_root_serves_landing(self, client: TestClient) -> None:
        resp = client.get("/", allow_redirects=False)
        assert resp.status_code == 200
        assert "SmartKCET" in resp.text

    def test_unauthenticated_index_html_serves_landing(self, client: TestClient) -> None:
        resp = client.get("/index.html", allow_redirects=False)
        assert resp.status_code == 200
        assert "SmartKCET" in resp.text

    def test_student_root_redirects_to_dashboard(
        self, client: TestClient, student_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, student_token)
        resp = client.get("/", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/dashboard"

    def test_admin_root_redirects_to_admin_upload(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, admin_token)
        resp = client.get("/", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/admin/upload"

    def test_admin_index_html_redirects_to_admin_upload(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, admin_token)
        resp = client.get("/index.html", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/admin/upload"


class TestPublicPages:
    """Tests for public pages that don't require auth."""

    def test_login_page_serves(self, client: TestClient) -> None:
        resp = client.get("/login", allow_redirects=False)
        assert resp.status_code == 200

    def test_register_page_serves(self, client: TestClient) -> None:
        resp = client.get("/register", allow_redirects=False)
        assert resp.status_code == 200


class TestDashboardPage:
    """Tests for /dashboard routing."""

    def test_unauthenticated_redirects_to_login(self, client: TestClient) -> None:
        resp = client.get("/dashboard", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_student_serves_dashboard(
        self, client: TestClient, student_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, student_token)
        resp = client.get("/dashboard", allow_redirects=False)
        assert resp.status_code == 200

    def test_admin_redirects_to_admin_upload(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, admin_token)
        resp = client.get("/dashboard", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/admin/upload"


class TestExamPage:
    """Tests for /exam routing."""

    def test_unauthenticated_redirects_to_login(self, client: TestClient) -> None:
        resp = client.get("/exam", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_student_serves_exam(
        self, client: TestClient, student_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, student_token)
        resp = client.get("/exam", allow_redirects=False)
        assert resp.status_code == 200


class TestAdminPages:
    """Tests for /admin/* routing."""

    def test_unauthenticated_admin_upload_redirects_to_login(
        self, client: TestClient
    ) -> None:
        resp = client.get("/admin/upload", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_student_admin_upload_redirects_to_dashboard(
        self, client: TestClient, student_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, student_token)
        resp = client.get("/admin/upload", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/dashboard"

    def test_admin_upload_serves_page(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, admin_token)
        resp = client.get("/admin/upload", allow_redirects=False)
        assert resp.status_code == 200

    def test_admin_questions_serves_page(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, admin_token)
        resp = client.get("/admin/questions", allow_redirects=False)
        assert resp.status_code == 200

    def test_admin_exams_serves_page(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, admin_token)
        resp = client.get("/admin/exams", allow_redirects=False)
        assert resp.status_code == 200

    def test_admin_analytics_serves_page(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, admin_token)
        resp = client.get("/admin/analytics", allow_redirects=False)
        assert resp.status_code == 200

    def test_admin_root_redirects_to_admin_upload(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, admin_token)
        resp = client.get("/admin", allow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/admin/upload"


class TestStaticAssets:
    """Tests for /css/* and /js/* static file serving."""

    def test_css_style_serves(self, client: TestClient) -> None:
        resp = client.get("/css/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers.get("content-type", "")

    def test_js_auth_serves(self, client: TestClient) -> None:
        resp = client.get("/js/auth.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers.get("content-type", "")
