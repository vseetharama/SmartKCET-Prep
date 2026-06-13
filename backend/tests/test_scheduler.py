"""Unit tests for SubscriptionScheduler.

Tests the subscription lifecycle scheduler including renewal processing,
grace period transitions, and expiry handling.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.subscription_models import (
    Subscription,
    SubscriptionEvent,
    SubscriptionPlan,
)
from smartkcet.subscription.scheduler import SubscriptionScheduler


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
        max_test_attempts_per_period=None,  # Unlimited
        is_active=True,
    )
    session.add(pro_weekly_plan)
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


@pytest.fixture
def pro_plan(db_session):
    """Get the Pro Weekly plan."""
    return db_session.query(SubscriptionPlan).filter(
        SubscriptionPlan.name == "Pro Weekly"
    ).first()


class TestProcessPendingRenewals:
    """Tests for process_pending_renewals method."""
    
    @pytest.mark.asyncio
    async def test_transitions_overdue_subscription_to_grace_period(
        self, db_session, test_user, pro_plan
    ):
        """Test that subscriptions past renewal date + 24h enter grace period."""
        # Create an active subscription past renewal date + 24h
        renewal_date = datetime.utcnow() - timedelta(hours=25)
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=test_user.id,
            plan_id=pro_plan.id,
            status="active",
            start_date=renewal_date - timedelta(days=7),
            current_period_start=renewal_date - timedelta(days=7),
            next_renewal_date=renewal_date,
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Process pending renewals
        scheduler = SubscriptionScheduler(db_session)
        count = await scheduler.process_pending_renewals()
        
        # Verify subscription transitioned to grace period
        assert count == 1
        db_session.refresh(subscription)
        assert subscription.status == "grace_period"
        assert subscription.grace_period_end is not None
        assert subscription.grace_period_end == renewal_date + timedelta(days=3)
        
        # Verify event was created
        event = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == "grace_period"
        ).first()
        assert event is not None
        assert event.previous_status == "active"
        assert event.new_status == "grace_period"
    
    @pytest.mark.asyncio
    async def test_does_not_process_subscription_within_24h(
        self, db_session, test_user, pro_plan
    ):
        """Test that subscriptions within 24h of renewal date are not processed."""
        # Create an active subscription past renewal date but within 24h
        renewal_date = datetime.utcnow() - timedelta(hours=12)
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=test_user.id,
            plan_id=pro_plan.id,
            status="active",
            start_date=renewal_date - timedelta(days=7),
            current_period_start=renewal_date - timedelta(days=7),
            next_renewal_date=renewal_date,
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Process pending renewals
        scheduler = SubscriptionScheduler(db_session)
        count = await scheduler.process_pending_renewals()
        
        # Verify subscription was not processed
        assert count == 0
        db_session.refresh(subscription)
        assert subscription.status == "active"
        assert subscription.grace_period_end is None
    
    @pytest.mark.asyncio
    async def test_handles_multiple_subscriptions(
        self, db_session, pro_plan
    ):
        """Test that multiple overdue subscriptions are processed."""
        renewal_date = datetime.utcnow() - timedelta(hours=25)
        
        # Create multiple users with overdue subscriptions
        for i in range(3):
            user = User(
                id=uuid.uuid4(),
                email=f"test{i}@example.com",
                kcet_student_id=f"TEST{i}",
                display_name=f"Test User {i}",
                password_hash="hashed_password",
                role="student",
                student_subtype="direct_subscriber",
            )
            db_session.add(user)
            
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
        
        # Process pending renewals
        scheduler = SubscriptionScheduler(db_session)
        count = await scheduler.process_pending_renewals()
        
        # Verify all subscriptions were processed
        assert count == 3
        
        # Verify all are in grace period
        grace_period_count = db_session.query(Subscription).filter(
            Subscription.status == "grace_period"
        ).count()
        assert grace_period_count == 3


class TestProcessGracePeriodExpirations:
    """Tests for process_grace_period_expirations method."""
    
    @pytest.mark.asyncio
    async def test_expires_subscription_past_grace_period(
        self, db_session, test_user, pro_plan
    ):
        """Test that subscriptions past grace period are expired."""
        # Create a subscription in grace period that has expired
        grace_period_end = datetime.utcnow() - timedelta(hours=1)
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=test_user.id,
            plan_id=pro_plan.id,
            status="grace_period",
            start_date=grace_period_end - timedelta(days=10),
            current_period_start=grace_period_end - timedelta(days=10),
            next_renewal_date=grace_period_end - timedelta(days=3),
            grace_period_end=grace_period_end,
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Process grace period expirations
        scheduler = SubscriptionScheduler(db_session)
        count = await scheduler.process_grace_period_expirations()
        
        # Verify subscription was expired
        assert count == 1
        db_session.refresh(subscription)
        assert subscription.status == "expired"
        
        # Verify event was created
        event = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == "expired"
        ).first()
        assert event is not None
        assert event.previous_status == "grace_period"
        assert event.new_status == "expired"
    
    @pytest.mark.asyncio
    async def test_does_not_expire_subscription_within_grace_period(
        self, db_session, test_user, pro_plan
    ):
        """Test that subscriptions still within grace period are not expired."""
        # Create a subscription in grace period that hasn't expired yet
        grace_period_end = datetime.utcnow() + timedelta(hours=12)
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=test_user.id,
            plan_id=pro_plan.id,
            status="grace_period",
            start_date=grace_period_end - timedelta(days=10),
            current_period_start=grace_period_end - timedelta(days=10),
            next_renewal_date=grace_period_end - timedelta(days=3),
            grace_period_end=grace_period_end,
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Process grace period expirations
        scheduler = SubscriptionScheduler(db_session)
        count = await scheduler.process_grace_period_expirations()
        
        # Verify subscription was not expired
        assert count == 0
        db_session.refresh(subscription)
        assert subscription.status == "grace_period"


class TestProcessPendingCancellations:
    """Tests for process_pending_cancellations method."""
    
    @pytest.mark.asyncio
    async def test_cancels_subscription_at_end_of_period(
        self, db_session, test_user, pro_plan
    ):
        """Test that subscriptions marked for cancellation are cancelled at period end."""
        # Create a subscription marked for cancellation past its renewal date
        renewal_date = datetime.utcnow() - timedelta(hours=1)
        cancellation_date = renewal_date - timedelta(days=3)
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=test_user.id,
            plan_id=pro_plan.id,
            status="active",
            start_date=renewal_date - timedelta(days=7),
            current_period_start=renewal_date - timedelta(days=7),
            next_renewal_date=renewal_date,
            cancellation_date=cancellation_date,
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Process pending cancellations
        scheduler = SubscriptionScheduler(db_session)
        count = await scheduler.process_pending_cancellations()
        
        # Verify subscription was cancelled
        assert count == 1
        db_session.refresh(subscription)
        assert subscription.status == "cancelled"
        
        # Verify event was created
        event = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == "cancelled"
        ).first()
        assert event is not None
        assert event.previous_status == "active"
        assert event.new_status == "cancelled"
    
    @pytest.mark.asyncio
    async def test_does_not_cancel_before_period_end(
        self, db_session, test_user, pro_plan
    ):
        """Test that subscriptions are not cancelled before period end."""
        # Create a subscription marked for cancellation but before renewal date
        renewal_date = datetime.utcnow() + timedelta(days=2)
        cancellation_date = datetime.utcnow() - timedelta(days=1)
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=test_user.id,
            plan_id=pro_plan.id,
            status="active",
            start_date=renewal_date - timedelta(days=7),
            current_period_start=renewal_date - timedelta(days=7),
            next_renewal_date=renewal_date,
            cancellation_date=cancellation_date,
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Process pending cancellations
        scheduler = SubscriptionScheduler(db_session)
        count = await scheduler.process_pending_cancellations()
        
        # Verify subscription was not cancelled
        assert count == 0
        db_session.refresh(subscription)
        assert subscription.status == "active"


class TestSubscriptionLifecycleTick:
    """Tests for subscription_lifecycle_tick method."""
    
    @pytest.mark.asyncio
    async def test_processes_all_lifecycle_events(
        self, db_session, pro_plan
    ):
        """Test that lifecycle tick processes renewals, expirations, and cancellations."""
        # Create subscriptions in different states
        
        # 1. Overdue subscription (should enter grace period)
        user1 = User(
            id=uuid.uuid4(),
            email="user1@example.com",
            kcet_student_id="USER1",
            display_name="User 1",
            password_hash="hashed_password",
            role="student",
            student_subtype="direct_subscriber",
        )
        db_session.add(user1)
        
        renewal_date1 = datetime.utcnow() - timedelta(hours=25)
        subscription1 = Subscription(
            id=uuid.uuid4(),
            user_id=user1.id,
            plan_id=pro_plan.id,
            status="active",
            start_date=renewal_date1 - timedelta(days=7),
            current_period_start=renewal_date1 - timedelta(days=7),
            next_renewal_date=renewal_date1,
        )
        db_session.add(subscription1)
        
        # 2. Grace period expired (should expire)
        user2 = User(
            id=uuid.uuid4(),
            email="user2@example.com",
            kcet_student_id="USER2",
            display_name="User 2",
            password_hash="hashed_password",
            role="student",
            student_subtype="direct_subscriber",
        )
        db_session.add(user2)
        
        grace_period_end2 = datetime.utcnow() - timedelta(hours=1)
        subscription2 = Subscription(
            id=uuid.uuid4(),
            user_id=user2.id,
            plan_id=pro_plan.id,
            status="grace_period",
            start_date=grace_period_end2 - timedelta(days=10),
            current_period_start=grace_period_end2 - timedelta(days=10),
            next_renewal_date=grace_period_end2 - timedelta(days=3),
            grace_period_end=grace_period_end2,
        )
        db_session.add(subscription2)
        
        # 3. Marked for cancellation (should cancel)
        user3 = User(
            id=uuid.uuid4(),
            email="user3@example.com",
            kcet_student_id="USER3",
            display_name="User 3",
            password_hash="hashed_password",
            role="student",
            student_subtype="direct_subscriber",
        )
        db_session.add(user3)
        
        renewal_date3 = datetime.utcnow() - timedelta(hours=1)
        subscription3 = Subscription(
            id=uuid.uuid4(),
            user_id=user3.id,
            plan_id=pro_plan.id,
            status="active",
            start_date=renewal_date3 - timedelta(days=7),
            current_period_start=renewal_date3 - timedelta(days=7),
            next_renewal_date=renewal_date3,
            cancellation_date=renewal_date3 - timedelta(days=3),
        )
        db_session.add(subscription3)
        
        db_session.commit()
        
        # Run lifecycle tick
        scheduler = SubscriptionScheduler(db_session)
        results = await scheduler.subscription_lifecycle_tick()
        
        # Verify results
        assert results["grace_period"] == 1
        assert results["expired"] == 1
        assert results["cancelled"] == 1
        assert results["errors"] == 0
        
        # Verify final states
        db_session.refresh(subscription1)
        assert subscription1.status == "grace_period"
        
        db_session.refresh(subscription2)
        assert subscription2.status == "expired"
        
        db_session.refresh(subscription3)
        assert subscription3.status == "cancelled"


class TestCleanupOldEvents:
    """Tests for cleanup_old_events method."""
    
    @pytest.mark.asyncio
    async def test_deletes_old_events(self, db_session, test_user, pro_plan):
        """Test that old subscription events are deleted."""
        # Create a subscription
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=test_user.id,
            plan_id=pro_plan.id,
            status="active",
            start_date=datetime.utcnow(),
            current_period_start=datetime.utcnow(),
            next_renewal_date=datetime.utcnow() + timedelta(days=7),
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Create old events (older than 90 days)
        old_event = SubscriptionEvent(
            id=uuid.uuid4(),
            subscription_id=subscription.id,
            event_type="activated",
            previous_status="none",
            new_status="active",
            event_metadata={},
            occurred_at=datetime.utcnow() - timedelta(days=100),
        )
        db_session.add(old_event)
        
        # Create recent event (within 90 days)
        recent_event = SubscriptionEvent(
            id=uuid.uuid4(),
            subscription_id=subscription.id,
            event_type="renewed",
            previous_status="active",
            new_status="active",
            event_metadata={},
            occurred_at=datetime.utcnow() - timedelta(days=30),
        )
        db_session.add(recent_event)
        db_session.commit()
        
        # Cleanup old events
        scheduler = SubscriptionScheduler(db_session)
        deleted_count = await scheduler.cleanup_old_events(days_to_keep=90)
        
        # Verify old event was deleted
        assert deleted_count == 1
        
        # Verify recent event still exists
        remaining_events = db_session.query(SubscriptionEvent).filter(
            SubscriptionEvent.subscription_id == subscription.id
        ).all()
        assert len(remaining_events) == 1
        assert remaining_events[0].id == recent_event.id
