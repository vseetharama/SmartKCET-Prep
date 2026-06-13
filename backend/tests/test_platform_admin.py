"""Tests for Platform Admin functionality.

This module tests:
- Admin authentication via environment variables
- Subscription plan CRUD operations
- Institution management (activate, suspend, remove)
- Aggregate analytics
- Audit logging for write operations
"""

import os
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.admin.platform_admin_service import PlatformAdminService
from smartkcet.db.base import Base
from smartkcet.db.models import Submission, User
from smartkcet.db.subscription_models import (
    BillingRecord,
    Institution,
    Subscription,
    SubscriptionPlan,
    UsageRecord,
)
from smartkcet.main import app


# Test database setup
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def platform_admin_service(db_session):
    """Create a PlatformAdminService instance."""
    return PlatformAdminService(db_session)


@pytest.fixture
def sample_subscription_plan(db_session):
    """Create a sample subscription plan."""
    plan = SubscriptionPlan(
        name="Test Pro Plan",
        plan_type="individual",
        billing_period="monthly",
        price=Decimal("99.99"),
        max_test_attempts_per_period=None,  # Unlimited
        feature_flags={},
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


@pytest.fixture
def sample_institution(db_session):
    """Create a sample institution."""
    institution = Institution(
        name="Test Institution",
        contact_phone="1234567890",
        subscription_status="inactive",
    )
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    return institution


@pytest.fixture
def sample_user(db_session):
    """Create a sample student user."""
    user = User(
        email="student@test.com",
        kcet_student_id="TEST123",
        display_name="Test Student",
        password_hash="hashed_password",
        role="student",
        student_subtype="direct_subscriber",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# -----------------------------------------------------------------------------
# Admin Authentication Tests
# -----------------------------------------------------------------------------


def test_get_admin_credentials_configured():
    """Test getting admin credentials when environment variables are set."""
    with patch.dict(os.environ, {
        "ADMIN_EMAIL": "admin@test.com",
        "ADMIN_PASSWORD_HASH": "hashed_password"
    }):
        credentials = PlatformAdminService.get_admin_credentials()
        assert credentials is not None
        assert credentials == ("admin@test.com", "hashed_password")


def test_get_admin_credentials_not_configured():
    """Test getting admin credentials when environment variables are not set."""
    with patch.dict(os.environ, {}, clear=True):
        credentials = PlatformAdminService.get_admin_credentials()
        assert credentials is None


def test_is_admin_configured():
    """Test checking if admin is configured."""
    with patch.dict(os.environ, {
        "ADMIN_EMAIL": "admin@test.com",
        "ADMIN_PASSWORD_HASH": "hashed_password"
    }):
        assert PlatformAdminService.is_admin_configured() is True
    
    with patch.dict(os.environ, {}, clear=True):
        assert PlatformAdminService.is_admin_configured() is False


def test_verify_admin_credentials_success(platform_admin_service):
    """Test verifying admin credentials successfully."""
    with patch.dict(os.environ, {
        "ADMIN_EMAIL": "admin@test.com",
        "ADMIN_PASSWORD_HASH": "hashed_password"
    }):
        result = platform_admin_service.verify_admin_credentials(
            "admin@test.com",
            "hashed_password"
        )
        assert result is True


def test_verify_admin_credentials_failure(platform_admin_service):
    """Test verifying admin credentials with wrong credentials."""
    with patch.dict(os.environ, {
        "ADMIN_EMAIL": "admin@test.com",
        "ADMIN_PASSWORD_HASH": "hashed_password"
    }):
        result = platform_admin_service.verify_admin_credentials(
            "wrong@test.com",
            "wrong_password"
        )
        assert result is False


def test_verify_admin_credentials_not_configured(platform_admin_service):
    """Test verifying admin credentials when not configured."""
    with patch.dict(os.environ, {}, clear=True):
        result = platform_admin_service.verify_admin_credentials(
            "admin@test.com",
            "hashed_password"
        )
        assert result is False


# -----------------------------------------------------------------------------
# Subscription Plan CRUD Tests
# -----------------------------------------------------------------------------


def test_create_subscription_plan_individual(platform_admin_service):
    """Test creating an individual subscription plan."""
    plan = platform_admin_service.create_subscription_plan(
        name="Pro Weekly",
        plan_type="individual",
        billing_period="weekly",
        price=Decimal("19.99"),
        max_test_attempts_per_period=None,  # Unlimited
        feature_flags={"full_analytics": True},
    )
    
    assert plan.name == "Pro Weekly"
    assert plan.plan_type == "individual"
    assert plan.billing_period == "weekly"
    assert plan.price == Decimal("19.99")
    assert plan.max_test_attempts_per_period is None
    assert plan.max_student_seats is None
    assert plan.feature_flags == {"full_analytics": True}
    assert plan.is_active is True


def test_create_subscription_plan_institution(platform_admin_service):
    """Test creating an institution subscription plan."""
    plan = platform_admin_service.create_subscription_plan(
        name="Institution Plan",
        plan_type="institution",
        billing_period="monthly",
        price=Decimal("999.99"),
        max_test_attempts_per_period=1000,
        max_student_seats=100,
        feature_flags={},
    )
    
    assert plan.name == "Institution Plan"
    assert plan.plan_type == "institution"
    assert plan.max_student_seats == 100


def test_create_subscription_plan_invalid_type(platform_admin_service):
    """Test creating a subscription plan with invalid type."""
    with pytest.raises(ValueError, match="Invalid plan_type"):
        platform_admin_service.create_subscription_plan(
            name="Invalid Plan",
            plan_type="invalid",
            billing_period="monthly",
            price=Decimal("99.99"),
        )


def test_create_subscription_plan_invalid_billing_period(platform_admin_service):
    """Test creating a subscription plan with invalid billing period."""
    with pytest.raises(ValueError, match="Invalid billing_period"):
        platform_admin_service.create_subscription_plan(
            name="Invalid Plan",
            plan_type="individual",
            billing_period="yearly",
            price=Decimal("99.99"),
        )


def test_create_subscription_plan_institution_missing_seats(platform_admin_service):
    """Test creating an institution plan without max_student_seats."""
    with pytest.raises(ValueError, match="max_student_seats is required"):
        platform_admin_service.create_subscription_plan(
            name="Institution Plan",
            plan_type="institution",
            billing_period="monthly",
            price=Decimal("999.99"),
        )


def test_get_subscription_plan(platform_admin_service, sample_subscription_plan):
    """Test getting a subscription plan by ID."""
    plan = platform_admin_service.get_subscription_plan(sample_subscription_plan.id)
    assert plan is not None
    assert plan.id == sample_subscription_plan.id
    assert plan.name == sample_subscription_plan.name


def test_get_subscription_plan_not_found(platform_admin_service):
    """Test getting a non-existent subscription plan."""
    plan = platform_admin_service.get_subscription_plan(uuid4())
    assert plan is None


def test_list_subscription_plans(platform_admin_service, db_session):
    """Test listing all subscription plans."""
    # Create multiple plans
    plan1 = SubscriptionPlan(
        name="Plan 1",
        plan_type="individual",
        billing_period="weekly",
        price=Decimal("19.99"),
        is_active=True,
    )
    plan2 = SubscriptionPlan(
        name="Plan 2",
        plan_type="institution",
        billing_period="monthly",
        price=Decimal("999.99"),
        max_student_seats=100,
        is_active=False,
    )
    db_session.add_all([plan1, plan2])
    db_session.commit()
    
    # List all plans
    all_plans = platform_admin_service.list_subscription_plans()
    assert len(all_plans) == 2
    
    # Filter by plan_type
    individual_plans = platform_admin_service.list_subscription_plans(plan_type="individual")
    assert len(individual_plans) == 1
    assert individual_plans[0].name == "Plan 1"
    
    # Filter by is_active
    active_plans = platform_admin_service.list_subscription_plans(is_active=True)
    assert len(active_plans) == 1
    assert active_plans[0].name == "Plan 1"


def test_update_subscription_plan(platform_admin_service, sample_subscription_plan):
    """Test updating a subscription plan."""
    updated_plan = platform_admin_service.update_subscription_plan(
        plan_id=sample_subscription_plan.id,
        name="Updated Plan Name",
        price=Decimal("149.99"),
        is_active=False,
    )
    
    assert updated_plan.name == "Updated Plan Name"
    assert updated_plan.price == Decimal("149.99")
    assert updated_plan.is_active is False


def test_update_subscription_plan_not_found(platform_admin_service):
    """Test updating a non-existent subscription plan."""
    with pytest.raises(ValueError, match="not found"):
        platform_admin_service.update_subscription_plan(
            plan_id=uuid4(),
            name="Updated Name",
        )


def test_delete_subscription_plan(platform_admin_service, sample_subscription_plan):
    """Test deleting a subscription plan with no active subscribers."""
    platform_admin_service.delete_subscription_plan(sample_subscription_plan.id)
    
    # Verify plan is deleted
    plan = platform_admin_service.get_subscription_plan(sample_subscription_plan.id)
    assert plan is None


def test_delete_subscription_plan_with_active_subscribers(
    platform_admin_service, sample_subscription_plan, sample_user, db_session
):
    """Test deleting a subscription plan with active subscribers."""
    from datetime import datetime
    
    # Create an active subscription
    now = datetime.utcnow()
    subscription = Subscription(
        user_id=sample_user.id,
        plan_id=sample_subscription_plan.id,
        status="active",
        start_date=now,
        current_period_start=now,
    )
    db_session.add(subscription)
    db_session.commit()
    
    # Attempt to delete plan
    with pytest.raises(ValueError, match="active subscribers"):
        platform_admin_service.delete_subscription_plan(sample_subscription_plan.id)


# -----------------------------------------------------------------------------
# Institution Management Tests
# -----------------------------------------------------------------------------


def test_activate_institution(platform_admin_service, sample_institution):
    """Test activating an institution."""
    institution = platform_admin_service.activate_institution(sample_institution.id)
    
    assert institution.subscription_status == "active"


def test_activate_institution_not_found(platform_admin_service):
    """Test activating a non-existent institution."""
    with pytest.raises(ValueError, match="not found"):
        platform_admin_service.activate_institution(uuid4())


def test_suspend_institution(platform_admin_service, sample_institution, db_session):
    """Test suspending an institution."""
    # First activate it
    sample_institution.subscription_status = "active"
    db_session.commit()
    
    # Then suspend it
    institution = platform_admin_service.suspend_institution(sample_institution.id)
    
    assert institution.subscription_status == "inactive"


def test_suspend_institution_not_found(platform_admin_service):
    """Test suspending a non-existent institution."""
    with pytest.raises(ValueError, match="not found"):
        platform_admin_service.suspend_institution(uuid4())


def test_remove_institution(platform_admin_service, sample_institution):
    """Test removing an institution."""
    platform_admin_service.remove_institution(sample_institution.id)
    
    # Verify institution is deleted
    institutions = platform_admin_service.list_institutions()
    assert len(institutions) == 0


def test_remove_institution_not_found(platform_admin_service):
    """Test removing a non-existent institution."""
    with pytest.raises(ValueError, match="not found"):
        platform_admin_service.remove_institution(uuid4())


def test_list_institutions(platform_admin_service, db_session):
    """Test listing institutions."""
    # Create multiple institutions
    inst1 = Institution(
        name="Institution 1",
        contact_phone="1234567890",
        subscription_status="active",
    )
    inst2 = Institution(
        name="Institution 2",
        contact_phone="0987654321",
        subscription_status="inactive",
    )
    db_session.add_all([inst1, inst2])
    db_session.commit()
    
    # List all institutions
    all_institutions = platform_admin_service.list_institutions()
    assert len(all_institutions) == 2
    
    # Filter by subscription_status
    active_institutions = platform_admin_service.list_institutions(subscription_status="active")
    assert len(active_institutions) == 1
    assert active_institutions[0].name == "Institution 1"


# -----------------------------------------------------------------------------
# Analytics Tests
# -----------------------------------------------------------------------------


def test_get_active_users_count(platform_admin_service, db_session):
    """Test getting active users count."""
    # Create test users
    admin = User(
        email="admin@test.com",
        display_name="Admin",
        password_hash="hash",
        role="platform_admin",
    )
    inst_admin = User(
        email="inst_admin@test.com",
        display_name="Inst Admin",
        password_hash="hash",
        role="institution_admin",
    )
    student1 = User(
        email="student1@test.com",
        kcet_student_id="S001",
        display_name="Student 1",
        password_hash="hash",
        role="student",
        student_subtype="direct_subscriber",
    )
    student2 = User(
        email="student2@test.com",
        kcet_student_id="S002",
        display_name="Student 2",
        password_hash="hash",
        role="student",
        student_subtype="institution_linked",
    )
    db_session.add_all([admin, inst_admin, student1, student2])
    db_session.commit()
    
    analytics = platform_admin_service.get_active_users_count()
    
    assert analytics["total_users"] == 4
    assert analytics["platform_admins"] == 1
    assert analytics["institution_admins"] == 1
    assert analytics["total_students"] == 2
    assert analytics["direct_subscribers"] == 1
    assert analytics["institution_linked"] == 1


def test_get_subscription_distribution(platform_admin_service, db_session, sample_user, sample_subscription_plan):
    """Test getting subscription distribution."""
    from datetime import datetime
    
    # Create test subscriptions
    now = datetime.utcnow()
    sub1 = Subscription(
        user_id=sample_user.id,
        plan_id=sample_subscription_plan.id,
        status="active",
        start_date=now,
        current_period_start=now,
    )
    db_session.add(sub1)
    db_session.commit()
    
    analytics = platform_admin_service.get_subscription_distribution()
    
    assert analytics["by_status"]["active"] == 1
    assert analytics["individual_subscriptions"] == 1
    assert analytics["institution_subscriptions"] == 0


def test_get_exam_attempts_statistics(platform_admin_service, db_session, sample_user):
    """Test getting exam attempt statistics."""
    # Create test submissions
    submission = Submission(
        user_id=sample_user.id,
        exam_set_id=uuid4(),
        answers={},
        score_pct=75.0,
        topic_breakdown={},
        time_taken_sec=3600,
        status="completed",
    )
    db_session.add(submission)
    db_session.commit()
    
    analytics = platform_admin_service.get_exam_attempts_statistics()
    
    assert analytics["total_attempts"] == 1


def test_get_revenue_statistics(platform_admin_service, db_session, sample_subscription_plan, sample_user):
    """Test getting revenue statistics."""
    from datetime import datetime
    
    # Create test subscription and billing record
    now = datetime.utcnow()
    subscription = Subscription(
        user_id=sample_user.id,
        plan_id=sample_subscription_plan.id,
        status="active",
        start_date=now,
        current_period_start=now,
    )
    db_session.add(subscription)
    db_session.flush()
    
    billing = BillingRecord(
        subscription_id=subscription.id,
        amount=Decimal("99.99"),
        billing_date=now,
        payment_status="paid",
    )
    db_session.add(billing)
    db_session.commit()
    
    analytics = platform_admin_service.get_revenue_statistics()
    
    assert analytics["total_revenue"] == "99.99"


def test_get_aggregate_analytics(platform_admin_service):
    """Test getting all aggregate analytics."""
    analytics = platform_admin_service.get_aggregate_analytics()
    
    assert "active_users" in analytics
    assert "subscription_distribution" in analytics
    assert "exam_attempts" in analytics
    assert "revenue" in analytics
    assert "generated_at" in analytics


# -----------------------------------------------------------------------------
# Audit Logging Tests
# -----------------------------------------------------------------------------


def test_audit_logging_create_plan(platform_admin_service, caplog):
    """Test that creating a plan logs the operation."""
    import logging
    caplog.set_level(logging.INFO)
    
    plan = platform_admin_service.create_subscription_plan(
        name="Test Plan",
        plan_type="individual",
        billing_period="monthly",
        price=Decimal("99.99"),
    )
    
    # Check that log was created
    assert any("create_subscription_plan" in record.message for record in caplog.records)


def test_audit_logging_update_plan(platform_admin_service, sample_subscription_plan, caplog):
    """Test that updating a plan logs the operation."""
    import logging
    caplog.set_level(logging.INFO)
    
    platform_admin_service.update_subscription_plan(
        plan_id=sample_subscription_plan.id,
        name="Updated Name",
    )
    
    # Check that log was created
    assert any("update_subscription_plan" in record.message for record in caplog.records)


def test_audit_logging_delete_plan(platform_admin_service, sample_subscription_plan, caplog):
    """Test that deleting a plan logs the operation."""
    import logging
    caplog.set_level(logging.INFO)
    
    platform_admin_service.delete_subscription_plan(sample_subscription_plan.id)
    
    # Check that log was created
    assert any("delete_subscription_plan" in record.message for record in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
