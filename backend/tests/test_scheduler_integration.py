"""Integration tests for subscription scheduler startup and shutdown.

Tests that the scheduler can be started and stopped correctly with the
FastAPI application lifecycle.
"""

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.subscription_models import Subscription, SubscriptionPlan
from smartkcet.subscription.scheduler import (
    get_scheduler_interval,
    start_subscription_scheduler,
    stop_subscription_scheduler,
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    # Create Pro Weekly plan
    pro_weekly_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Pro Weekly",
        plan_type="individual",
        billing_period="weekly",
        price=99.0,
        max_test_attempts_per_period=None,
        is_active=True,
    )
    session.add(pro_weekly_plan)
    session.commit()
    
    yield session
    
    session.close()


class TestSchedulerStartupShutdown:
    """Tests for scheduler startup and shutdown."""
    
    @pytest.mark.asyncio
    async def test_scheduler_can_be_started_and_stopped(self, db_session):
        """Test that the scheduler can be started and stopped without errors."""
        # Start the scheduler with a short interval for testing
        await start_subscription_scheduler(db_session, interval_minutes=1)
        
        # Wait a moment to ensure the task is running
        await asyncio.sleep(0.1)
        
        # Stop the scheduler
        await stop_subscription_scheduler()
        
        # Verify no errors occurred
        assert True
    
    @pytest.mark.asyncio
    async def test_scheduler_processes_subscriptions_on_tick(self, db_session):
        """Test that the scheduler processes subscriptions when it ticks."""
        # Create a test user
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
        
        # Get the Pro Weekly plan
        pro_plan = db_session.query(SubscriptionPlan).filter(
            SubscriptionPlan.name == "Pro Weekly"
        ).first()
        
        # Create an overdue subscription
        renewal_date = datetime.utcnow() - timedelta(hours=25)
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=user.id,
            plan_id=pro_plan.id,
            status="active",
            start_date=renewal_date - timedelta(days=7),
            current_period_start=renewal_date - timedelta(days=7),
            next_renewal_date=renewal_date,
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Manually trigger a scheduler tick
        from smartkcet.subscription.scheduler import SubscriptionScheduler
        
        scheduler = SubscriptionScheduler(db_session)
        results = await scheduler.subscription_lifecycle_tick()
        
        # Verify the subscription was processed
        assert results["grace_period"] == 1
        assert results["errors"] == 0
        
        # Verify the subscription is now in grace period
        db_session.refresh(subscription)
        assert subscription.status == "grace_period"


class TestGetSchedulerInterval:
    """Tests for get_scheduler_interval function."""
    
    def test_returns_default_interval_when_not_set(self, monkeypatch):
        """Test that default interval is returned when env var is not set."""
        monkeypatch.delenv("SUBSCRIPTION_SCHEDULER_INTERVAL_MINUTES", raising=False)
        
        interval = get_scheduler_interval()
        
        assert interval == 60
    
    def test_returns_configured_interval(self, monkeypatch):
        """Test that configured interval is returned when env var is set."""
        monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_INTERVAL_MINUTES", "30")
        
        interval = get_scheduler_interval()
        
        assert interval == 30
    
    def test_returns_default_for_invalid_interval(self, monkeypatch):
        """Test that default interval is returned for invalid values."""
        monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_INTERVAL_MINUTES", "invalid")
        
        interval = get_scheduler_interval()
        
        assert interval == 60
    
    def test_returns_default_for_negative_interval(self, monkeypatch):
        """Test that default interval is returned for negative values."""
        monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_INTERVAL_MINUTES", "-10")
        
        interval = get_scheduler_interval()
        
        assert interval == 60
