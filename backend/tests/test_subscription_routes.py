"""Integration tests for subscription API routes.

Tests the subscription endpoints to ensure they handle requests correctly,
enforce authentication, and return appropriate error responses.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from uuid import uuid4

from smartkcet.main import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_user():
    """Create a mock user object."""
    user = Mock()
    user.id = uuid4()
    user.role = "student"
    user.email = "test@example.com"
    return user


class TestSubscriptionRoutes:
    """Test suite for subscription API routes."""

    def test_select_endpoint_requires_authentication(self, client):
        """Test that /select endpoint requires authentication."""
        response = client.post(
            "/api/subscription/select",
            json={"plan_type": "trial"}
        )
        assert response.status_code == 401

    def test_status_endpoint_requires_authentication(self, client):
        """Test that /status endpoint requires authentication."""
        response = client.get("/api/subscription/status")
        assert response.status_code == 401

    def test_upgrade_endpoint_requires_authentication(self, client):
        """Test that /upgrade endpoint requires authentication."""
        response = client.post(
            "/api/subscription/upgrade",
            json={"billing_period": "weekly"}
        )
        assert response.status_code == 401

    def test_cancel_endpoint_requires_authentication(self, client):
        """Test that /cancel endpoint requires authentication."""
        response = client.post("/api/subscription/cancel")
        assert response.status_code == 401

    def test_reactivate_endpoint_requires_authentication(self, client):
        """Test that /reactivate endpoint requires authentication."""
        response = client.post(
            "/api/subscription/reactivate",
            json={"billing_period": "monthly"}
        )
        assert response.status_code == 401

    def test_select_validates_plan_type(self, client, mock_user):
        """Test that /select validates plan_type field."""
        with patch("smartkcet.subscription.routes.current_user", return_value=mock_user):
            with patch("smartkcet.subscription.routes.require_authenticated", return_value={}):
                response = client.post(
                    "/api/subscription/select",
                    json={"plan_type": "invalid"}
                )
                # Should fail validation (either 400 or 422)
                assert response.status_code in [400, 422]

    def test_select_requires_billing_period_for_pro(self, client, mock_user):
        """Test that /select requires billing_period for Pro subscriptions."""
        with patch("smartkcet.subscription.routes.current_user", return_value=mock_user):
            with patch("smartkcet.subscription.routes.require_authenticated", return_value={}):
                response = client.post(
                    "/api/subscription/select",
                    json={"plan_type": "pro"}
                )
                # Should fail validation
                assert response.status_code in [400, 422]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
