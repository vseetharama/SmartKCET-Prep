"""Integration tests for student routes with subscription wiring.

Tests that subscription status and remaining attempts are properly
integrated into student exam selection and dashboard endpoints.

**Validates: Requirements 1.5, 2.4, 3.8, 5.2**
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from smartkcet.db.models import User
from smartkcet.db.subscription_models import Subscription, SubscriptionPlan
from smartkcet.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def db_session():
    """Get a database session."""
    from smartkcet.db.session import get_session
    session = next(get_session())
    try:
        yield session
    finally:
        session.close()


def test_exam_list_includes_remaining_attempts(client: TestClient, db_session: Session):
    """Test that exam list endpoint includes remaining attempts data.
    
    **Validates: Requirements 1.5, 2.4**
    """
    # Find a student with an active subscription
    student = (
        db_session.query(User)
        .filter(User.role == "student")
        .first()
    )
    
    if not student:
        pytest.skip("No student user found in database")
    
    # Check if student has an active subscription
    subscription = (
        db_session.query(Subscription)
        .filter(
            Subscription.user_id == student.id,
            Subscription.status.in_(["trial", "active", "grace_period"])
        )
        .first()
    )
    
    if not subscription:
        pytest.skip("No active subscription found for student")
    
    # Create a session token for the student
    from smartkcet.auth.tokens import issue_token
    token, _, _, _ = issue_token(
        sub=str(student.id),
        role="student",
        student_subtype="direct_subscriber",
        subscription_status=subscription.status,
    )
    
    # Make request to exam list endpoint
    client.cookies.set("Session_Token", token)
    response = client.get("/api/student/exams")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response includes remaining_attempts
    assert "remaining_attempts" in data
    
    if data["remaining_attempts"] is not None:
        # Verify structure of remaining_attempts
        assert "total_attempts" in data["remaining_attempts"]
        assert "is_unlimited" in data["remaining_attempts"]


def test_submissions_list_includes_subscription_status(client: TestClient, db_session: Session):
    """Test that submissions list endpoint includes subscription status.
    
    **Validates: Requirements 2.4**
    """
    # Find a student with an active subscription
    student = (
        db_session.query(User)
        .filter(User.role == "student")
        .first()
    )
    
    if not student:
        pytest.skip("No student user found in database")
    
    # Check if student has an active subscription
    subscription = (
        db_session.query(Subscription)
        .filter(
            Subscription.user_id == student.id,
            Subscription.status.in_(["trial", "active", "grace_period"])
        )
        .first()
    )
    
    if not subscription:
        pytest.skip("No active subscription found for student")
    
    # Create a session token for the student
    from smartkcet.auth.tokens import issue_token
    token, _, _, _ = issue_token(
        sub=str(student.id),
        role="student",
        student_subtype="direct_subscriber",
        subscription_status=subscription.status,
    )
    
    # Make request to submissions list endpoint
    client.cookies.set("Session_Token", token)
    response = client.get("/api/student/submissions")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response includes subscription_status
    assert "subscription_status" in data
    
    if data["subscription_status"] is not None:
        # Verify structure of subscription_status
        assert "has_subscription" in data["subscription_status"]
        assert "status" in data["subscription_status"]
        assert "is_trial" in data["subscription_status"]
        assert "is_active" in data["subscription_status"]
    
    # Verify response includes remaining_attempts
    assert "remaining_attempts" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
