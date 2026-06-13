"""Unit tests for SubscriptionService.

Tests the core subscription lifecycle methods including activation,
status queries, and idempotency.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.subscription_models import (
    Institution,
    Subscription,
    SubscriptionEvent,
    SubscriptionPlan,
)
from smartkcet.subscription.models import BillingPeriod
from smartkcet.subscription.service import SubscriptionService


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    # Create Free Trial plan
    free_trial_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Free Trial",
        plan_type="individual",
        billing_period="weekly",
        price=0.0,
        max_test_attempts_per_period=5,
        is_active=True,
    )
    session.add(free_trial_plan)
    
    # Create Pro Weekly plan
    pro_weekly_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Pro Weekly",
        plan_type="individual",
        billing_period="weekly",
        price=99.0,
        max_test_attempts_per_period=None,  # Unlimited
        is_active=True,
    )
    session.add(pro_weekly_plan)
    
    # Create Pro Monthly plan
    pro_monthly_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Pro Monthly",
        plan_type="individual",
        billing_period="monthly",
        price=299.0,
        max_test_attempts_per_period=None,  # Unlimited
        is_active=True,
    )
    session.add(pro_monthly_plan)
    
    session.commit()
    
    yield session
    
    session.close()


@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        kcet_student_id="TEST123",
        display_name="Test User",
        password_hash="hashed_password",
        role="student",
        student_subtype="direct_subscriber",
    )
    db_session.add(user)
    db_session.commit()
    return user


class TestActivateTrial:
    """Tests for activate_trial method."""
    
    def test_activate_trial_creates_subscription(self, db_session, test_user):
        """Test that activate_trial creates a new trial subscription."""
        service = SubscriptionService(db_session)
        
        subscription = service.activate_trial(test_user.id, duration_days=7)
        
        assert subscription is not None
        assert subscription.user_id == test_user.id
        assert subscription.status == "trial"
        assert subscription.trial_duration_days == 7
        assert subscription.next_renewal_date is None
        
    def test_activate_trial_custom_duration(self, db_session, test_user):
        """Test that activate_trial accepts custom duration."""
        service = SubscriptionService(db_session)
        
        subscription = service.activate_trial(test_user.id, duration_days=14)
        
        assert subscription.trial_duration_days == 14
        
    def test_activate_trial_idempotent(self, db_session, test_user):
        """Test that activate_trial is idempotent."""
        service = SubscriptionService(db_session)
        
        # First activation
        subscription1 = service.activate_trial(test_user.id, duration_days=7)
        
        # Second activation should return the same subscription
        subscription2 = service.activate_trial(test_user.id, duration_days=14)
        
        assert subscription1.id == subscription2.id
        assert subscription2.trial_duration_days == 7  # Original duration preserved
        
    def test_activate_trial_invalid_duration(self, db_session, test_user):
        """Test that activate_trial rejects invalid duration."""
        service = SubscriptionService(db_session)
        
        # Duration too short
        with pytest.raises(ValueError, match="between 1 and 90 days"):
            service.activate_trial(test_user.id, duration_days=0)
        
        # Duration too long
        with pytest.raises(ValueError, match="between 1 and 90 days"):
            service.activate_trial(test_user.id, duration_days=91)
            
    def test_activate_trial_creates_event(self, db_session, test_user):
        """Test that activate_trial creates a subscription event."""
        service = SubscriptionService(db_session)
        
        subscription = service.activate_trial(test_user.id, duration_days=7)
        
        # Check that event was created
        event = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id
        ).first()
        
        assert event is not None
        assert event.event_type == "activated"
        assert event.previous_status == "none"
        assert event.new_status == "trial"


class TestActivatePro:
    """Tests for activate_pro method."""
    
    def test_activate_pro_weekly(self, db_session, test_user):
        """Test that activate_pro creates a weekly Pro subscription."""
        service = SubscriptionService(db_session)
        
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        assert subscription is not None
        assert subscription.user_id == test_user.id
        assert subscription.status == "active"
        assert subscription.next_renewal_date is not None
        
        # Check renewal date is 7 days from now
        expected_renewal = subscription.start_date + timedelta(days=7)
        assert abs((subscription.next_renewal_date - expected_renewal).total_seconds()) < 1
        
    def test_activate_pro_monthly(self, db_session, test_user):
        """Test that activate_pro creates a monthly Pro subscription."""
        service = SubscriptionService(db_session)
        
        subscription = service.activate_pro(test_user.id, BillingPeriod.MONTHLY)
        
        assert subscription is not None
        assert subscription.status == "active"
        
        # Check renewal date is 30 days from now
        expected_renewal = subscription.start_date + timedelta(days=30)
        assert abs((subscription.next_renewal_date - expected_renewal).total_seconds()) < 1
        
    def test_activate_pro_idempotent(self, db_session, test_user):
        """Test that activate_pro is idempotent."""
        service = SubscriptionService(db_session)
        
        # First activation
        subscription1 = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Second activation should return the same subscription
        subscription2 = service.activate_pro(test_user.id, BillingPeriod.MONTHLY)
        
        assert subscription1.id == subscription2.id
        
    def test_activate_pro_creates_event(self, db_session, test_user):
        """Test that activate_pro creates a subscription event."""
        service = SubscriptionService(db_session)
        
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Check that event was created
        event = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id
        ).first()
        
        assert event is not None
        assert event.event_type == "activated"
        assert event.previous_status == "none"
        assert event.new_status == "active"


class TestGetEffectiveStatus:
    """Tests for get_effective_status method."""
    
    def test_get_effective_status_no_subscription(self, db_session, test_user):
        """Test get_effective_status when user has no subscription."""
        service = SubscriptionService(db_session)
        
        status = service.get_effective_status(test_user.id)
        
        assert status.has_subscription is False
        assert status.status is None
        assert status.is_active is False
        
    def test_get_effective_status_trial(self, db_session, test_user):
        """Test get_effective_status for trial subscription."""
        service = SubscriptionService(db_session)
        
        # Create trial subscription
        subscription = service.activate_trial(test_user.id, duration_days=7)
        
        status = service.get_effective_status(test_user.id)
        
        assert status.has_subscription is True
        assert status.status == "trial"
        assert status.is_trial is True
        assert status.is_active is True
        assert status.trial_attempts_remaining == 5  # No submissions yet
        
    def test_get_effective_status_pro(self, db_session, test_user):
        """Test get_effective_status for Pro subscription."""
        service = SubscriptionService(db_session)
        
        # Create Pro subscription
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        status = service.get_effective_status(test_user.id)
        
        assert status.has_subscription is True
        assert status.status == "active"
        assert status.is_trial is False
        assert status.is_active is True
        assert status.trial_attempts_remaining is None  # Not a trial
        assert status.next_renewal_date is not None


class TestProcessRenewal:
    """Tests for process_renewal method."""
    
    def test_process_renewal_with_payment(self, db_session, test_user):
        """Test that process_renewal extends subscription when payment confirmed."""
        service = SubscriptionService(db_session)
        
        # Create Pro subscription
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        original_renewal_date = subscription.next_renewal_date
        
        # Process renewal with payment
        updated_subscription = service.process_renewal(subscription.id, payment_confirmed=True)
        
        assert updated_subscription.status == "active"
        assert updated_subscription.grace_period_end is None
        # Renewal date should be extended by 7 days
        expected_new_renewal = original_renewal_date + timedelta(days=7)
        assert abs((updated_subscription.next_renewal_date - expected_new_renewal).total_seconds()) < 1
        
    def test_process_renewal_without_payment(self, db_session, test_user):
        """Test that process_renewal enters grace period when payment not confirmed."""
        service = SubscriptionService(db_session)
        
        # Create Pro subscription
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        original_renewal_date = subscription.next_renewal_date
        
        # Process renewal without payment
        updated_subscription = service.process_renewal(subscription.id, payment_confirmed=False)
        
        assert updated_subscription.status == "grace_period"
        assert updated_subscription.grace_period_end is not None
        # Grace period should be 3 days from renewal date
        expected_grace_end = original_renewal_date + timedelta(days=3)
        assert abs((updated_subscription.grace_period_end - expected_grace_end).total_seconds()) < 1
        
    def test_process_renewal_monthly(self, db_session, test_user):
        """Test that process_renewal handles monthly billing correctly."""
        service = SubscriptionService(db_session)
        
        # Create monthly Pro subscription
        subscription = service.activate_pro(test_user.id, BillingPeriod.MONTHLY)
        original_renewal_date = subscription.next_renewal_date
        
        # Process renewal with payment
        updated_subscription = service.process_renewal(subscription.id, payment_confirmed=True)
        
        # Renewal date should be extended by 30 days
        expected_new_renewal = original_renewal_date + timedelta(days=30)
        assert abs((updated_subscription.next_renewal_date - expected_new_renewal).total_seconds()) < 1
        
    def test_process_renewal_creates_event(self, db_session, test_user):
        """Test that process_renewal creates a subscription event."""
        service = SubscriptionService(db_session)
        
        # Create Pro subscription
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Process renewal
        service.process_renewal(subscription.id, payment_confirmed=True)
        
        # Check that renewal event was created
        events = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == "renewed"
        ).all()
        
        assert len(events) == 1
        assert events[0].new_status == "active"
        
    def test_process_renewal_invalid_subscription(self, db_session):
        """Test that process_renewal raises error for invalid subscription."""
        service = SubscriptionService(db_session)
        
        with pytest.raises(ValueError, match="not found"):
            service.process_renewal(uuid.uuid4(), payment_confirmed=True)


class TestCancelSubscription:
    """Tests for cancel_subscription method."""
    
    def test_cancel_subscription_marks_for_cancellation(self, db_session, test_user):
        """Test that cancel_subscription marks subscription for cancellation."""
        service = SubscriptionService(db_session)
        
        # Create Pro subscription
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        original_status = subscription.status
        
        # Cancel subscription
        cancelled_subscription = service.cancel_subscription(subscription.id)
        
        assert cancelled_subscription.cancellation_date is not None
        # Status should remain active until end of billing period
        assert cancelled_subscription.status == original_status
        
    def test_cancel_subscription_creates_event(self, db_session, test_user):
        """Test that cancel_subscription creates a subscription event."""
        service = SubscriptionService(db_session)
        
        # Create Pro subscription
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Cancel subscription
        service.cancel_subscription(subscription.id)
        
        # Check that cancellation event was created
        events = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == "cancelled"
        ).all()
        
        assert len(events) == 1
        assert events[0].event_metadata.get("cancellation_requested_at") is not None
        
    def test_cancel_subscription_invalid_subscription(self, db_session):
        """Test that cancel_subscription raises error for invalid subscription."""
        service = SubscriptionService(db_session)
        
        with pytest.raises(ValueError, match="not found"):
            service.cancel_subscription(uuid.uuid4())


class TestReactivate:
    """Tests for reactivate method."""
    
    def test_reactivate_creates_new_subscription(self, db_session, test_user):
        """Test that reactivate creates a new active subscription."""
        service = SubscriptionService(db_session)
        
        # Create and expire a subscription (simulate expired state)
        old_subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        old_subscription.status = "expired"
        db_session.commit()
        
        # Reactivate
        new_subscription = service.reactivate(test_user.id, BillingPeriod.MONTHLY)
        
        assert new_subscription.id != old_subscription.id
        assert new_subscription.status == "active"
        assert new_subscription.user_id == test_user.id
        
    def test_reactivate_calculates_renewal_date(self, db_session, test_user):
        """Test that reactivate calculates correct renewal date."""
        service = SubscriptionService(db_session)
        
        # Reactivate with weekly billing
        subscription = service.reactivate(test_user.id, BillingPeriod.WEEKLY)
        
        expected_renewal = subscription.start_date + timedelta(days=7)
        assert abs((subscription.next_renewal_date - expected_renewal).total_seconds()) < 1
        
    def test_reactivate_preserves_history(self, db_session, test_user):
        """Test that reactivate preserves exam history (user record unchanged)."""
        service = SubscriptionService(db_session)
        
        # Create and expire a subscription
        old_subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        old_subscription.status = "expired"
        db_session.commit()
        
        # Reactivate
        new_subscription = service.reactivate(test_user.id, BillingPeriod.MONTHLY)
        
        # User should still exist with same ID
        user = db_session.query(User).filter(User.id == test_user.id).first()
        assert user is not None
        assert user.id == test_user.id
        
    def test_reactivate_creates_event(self, db_session, test_user):
        """Test that reactivate creates a subscription event."""
        service = SubscriptionService(db_session)
        
        # Reactivate
        subscription = service.reactivate(test_user.id, BillingPeriod.WEEKLY)
        
        # Check that reactivation event was created
        events = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == "reactivated"
        ).all()
        
        assert len(events) == 1
        assert events[0].new_status == "active"
        
    def test_reactivate_with_active_subscription_fails(self, db_session, test_user):
        """Test that reactivate fails if user already has active subscription."""
        service = SubscriptionService(db_session)
        
        # Create active subscription
        service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Try to reactivate
        with pytest.raises(ValueError, match="already has an active subscription"):
            service.reactivate(test_user.id, BillingPeriod.MONTHLY)


class TestUpgradeTrialToPro:
    """Tests for upgrade_trial_to_pro method."""
    
    def test_upgrade_trial_to_pro_converts_subscription(self, db_session, test_user):
        """Test that upgrade_trial_to_pro converts trial to Pro."""
        service = SubscriptionService(db_session)
        
        # Create trial subscription
        trial_subscription = service.activate_trial(test_user.id, duration_days=7)
        trial_id = trial_subscription.id
        
        # Upgrade to Pro
        upgraded_subscription = service.upgrade_trial_to_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Should be the same subscription record, just updated
        assert upgraded_subscription.id == trial_id
        assert upgraded_subscription.status == "active"
        assert upgraded_subscription.trial_duration_days is None
        assert upgraded_subscription.next_renewal_date is not None
        
    def test_upgrade_trial_to_pro_calculates_renewal_date(self, db_session, test_user):
        """Test that upgrade_trial_to_pro calculates correct renewal date."""
        service = SubscriptionService(db_session)
        
        # Create trial subscription
        service.activate_trial(test_user.id, duration_days=7)
        
        # Upgrade to Pro with monthly billing
        upgraded_subscription = service.upgrade_trial_to_pro(test_user.id, BillingPeriod.MONTHLY)
        
        expected_renewal = upgraded_subscription.current_period_start + timedelta(days=30)
        assert abs((upgraded_subscription.next_renewal_date - expected_renewal).total_seconds()) < 1
        
    def test_upgrade_trial_to_pro_preserves_history(self, db_session, test_user):
        """Test that upgrade_trial_to_pro preserves subscription history."""
        service = SubscriptionService(db_session)
        
        # Create trial subscription
        trial_subscription = service.activate_trial(test_user.id, duration_days=7)
        trial_start_date = trial_subscription.start_date
        
        # Upgrade to Pro
        upgraded_subscription = service.upgrade_trial_to_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Original start date should be preserved
        assert upgraded_subscription.start_date == trial_start_date
        
    def test_upgrade_trial_to_pro_creates_event(self, db_session, test_user):
        """Test that upgrade_trial_to_pro creates a subscription event."""
        service = SubscriptionService(db_session)
        
        # Create trial subscription
        trial_subscription = service.activate_trial(test_user.id, duration_days=7)
        
        # Upgrade to Pro
        service.upgrade_trial_to_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Check that upgrade event was created
        events = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == trial_subscription.id,
            SubscriptionEvent.event_type == "upgraded"
        ).all()
        
        assert len(events) == 1
        assert events[0].previous_status == "trial"
        assert events[0].new_status == "active"
        
    def test_upgrade_trial_to_pro_without_trial_fails(self, db_session, test_user):
        """Test that upgrade_trial_to_pro fails if user has no trial."""
        service = SubscriptionService(db_session)
        
        # Try to upgrade without trial
        with pytest.raises(ValueError, match="No active trial subscription found"):
            service.upgrade_trial_to_pro(test_user.id, BillingPeriod.WEEKLY)
