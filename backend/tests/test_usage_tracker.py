"""Unit tests for UsageTracker.

Tests the usage tracking and quota enforcement functionality.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.subscription_models import (
    Institution,
    Subscription,
    SubscriptionPlan,
    UsageRecord,
)
from smartkcet.subscription.usage import UsageTracker


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()


@pytest.fixture
def free_trial_plan(db_session):
    """Create a Free Trial plan."""
    plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Free Trial",
        plan_type="individual",
        billing_period="weekly",
        price=0.0,
        max_test_attempts_per_period=5,
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    return plan


@pytest.fixture
def pro_weekly_plan(db_session):
    """Create a Pro Weekly plan."""
    plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Pro Weekly",
        plan_type="individual",
        billing_period="weekly",
        price=9.99,
        max_test_attempts_per_period=None,  # Unlimited
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    return plan


@pytest.fixture
def institution_plan(db_session):
    """Create an institution plan with limited tests."""
    plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Institution Basic",
        plan_type="institution",
        billing_period="monthly",
        price=499.99,
        max_test_attempts_per_period=100,
        max_student_seats=50,
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    return plan


@pytest.fixture
def trial_user(db_session, free_trial_plan):
    """Create a user with a Free Trial subscription."""
    user = User(
        id=uuid.uuid4(),
        email="trial@example.com",
        kcet_student_id="TRIAL001",
        display_name="Trial User",
        password_hash="hashed",
        role="student",
        student_subtype="direct_subscriber",
    )
    db_session.add(user)
    db_session.flush()
    
    subscription = Subscription(
        id=uuid.uuid4(),
        user_id=user.id,
        plan_id=free_trial_plan.id,
        status="trial",
        start_date=datetime.utcnow(),
        current_period_start=datetime.utcnow(),
        trial_duration_days=7,
    )
    db_session.add(subscription)
    db_session.commit()
    
    return user


@pytest.fixture
def pro_user(db_session, pro_weekly_plan):
    """Create a user with a Pro subscription."""
    user = User(
        id=uuid.uuid4(),
        email="pro@example.com",
        kcet_student_id="PRO001",
        display_name="Pro User",
        password_hash="hashed",
        role="student",
        student_subtype="direct_subscriber",
    )
    db_session.add(user)
    db_session.flush()
    
    subscription = Subscription(
        id=uuid.uuid4(),
        user_id=user.id,
        plan_id=pro_weekly_plan.id,
        status="active",
        start_date=datetime.utcnow(),
        current_period_start=datetime.utcnow(),
        next_renewal_date=datetime.utcnow() + timedelta(days=7),
    )
    db_session.add(subscription)
    db_session.commit()
    
    return user


@pytest.fixture
def institution_with_subscription(db_session, institution_plan):
    """Create an institution with an active subscription."""
    institution = Institution(
        id=uuid.uuid4(),
        name="Test Institution",
        contact_phone="1234567890",
        subscription_status="active",
    )
    db_session.add(institution)
    db_session.flush()
    
    subscription = Subscription(
        id=uuid.uuid4(),
        institution_id=institution.id,
        plan_id=institution_plan.id,
        status="active",
        start_date=datetime.utcnow(),
        current_period_start=datetime.utcnow(),
        next_renewal_date=datetime.utcnow() + timedelta(days=30),
    )
    db_session.add(subscription)
    db_session.commit()
    
    return institution


@pytest.fixture
def institution_user(db_session, institution_with_subscription):
    """Create a user linked to an institution."""
    user = User(
        id=uuid.uuid4(),
        email="inst@example.com",
        kcet_student_id="INST001",
        display_name="Institution User",
        password_hash="hashed",
        role="student",
        student_subtype="institution_linked",
        institution_id=institution_with_subscription.id,
    )
    db_session.add(user)
    db_session.commit()
    
    return user


class TestCanStartExam:
    """Tests for UsageTracker.can_start_exam()."""
    
    def test_trial_user_with_no_attempts(self, db_session, trial_user):
        """Trial user with 0 attempts should be allowed to start exam."""
        tracker = UsageTracker(db_session)
        result = tracker.can_start_exam(trial_user.id)
        
        assert result.can_start is True
        assert result.remaining_attempts == 5
        assert result.quota_type == "trial"
    
    def test_trial_user_with_4_attempts(self, db_session, trial_user):
        """Trial user with 4 attempts should have 1 remaining."""
        tracker = UsageTracker(db_session)
        
        # Create 4 usage records
        for i in range(4):
            usage = UsageRecord(
                id=uuid.uuid4(),
                user_id=trial_user.id,
                submission_id=uuid.uuid4(),
                subject="Physics",
                billing_period_start=datetime.utcnow(),
            )
            db_session.add(usage)
        db_session.commit()
        
        result = tracker.can_start_exam(trial_user.id)
        
        assert result.can_start is True
        assert result.remaining_attempts == 1
        assert result.quota_type == "trial"
    
    def test_trial_user_with_5_attempts(self, db_session, trial_user):
        """Trial user with 5 attempts should be blocked."""
        tracker = UsageTracker(db_session)
        
        # Create 5 usage records
        for i in range(5):
            usage = UsageRecord(
                id=uuid.uuid4(),
                user_id=trial_user.id,
                submission_id=uuid.uuid4(),
                subject="Physics",
                billing_period_start=datetime.utcnow(),
            )
            db_session.add(usage)
        db_session.commit()
        
        result = tracker.can_start_exam(trial_user.id)
        
        assert result.can_start is False
        assert result.remaining_attempts == 0
        assert result.quota_type == "trial"
        assert "Trial attempt limit reached" in result.reason
    
    def test_pro_user_unlimited_attempts(self, db_session, pro_user):
        """Pro user should have unlimited attempts."""
        tracker = UsageTracker(db_session)
        
        # Create 100 usage records (way more than trial limit)
        for i in range(100):
            usage = UsageRecord(
                id=uuid.uuid4(),
                user_id=pro_user.id,
                submission_id=uuid.uuid4(),
                subject="Physics",
                billing_period_start=datetime.utcnow(),
            )
            db_session.add(usage)
        db_session.commit()
        
        result = tracker.can_start_exam(pro_user.id)
        
        assert result.can_start is True
        assert result.remaining_attempts is None  # Unlimited
        assert result.quota_type == "unlimited"
    
    def test_user_without_subscription(self, db_session):
        """User without subscription should be blocked."""
        user = User(
            id=uuid.uuid4(),
            email="nosub@example.com",
            kcet_student_id="NOSUB001",
            display_name="No Sub User",
            password_hash="hashed",
            role="student",
            student_subtype="direct_subscriber",
        )
        db_session.add(user)
        db_session.commit()
        
        tracker = UsageTracker(db_session)
        result = tracker.can_start_exam(user.id)
        
        assert result.can_start is False
        assert "No active subscription" in result.reason


class TestRecordAttempt:
    """Tests for UsageTracker.record_attempt()."""
    
    def test_record_attempt_for_trial_user(self, db_session, trial_user):
        """Recording an attempt should create a usage record."""
        tracker = UsageTracker(db_session)
        submission_id = uuid.uuid4()
        
        tracker.record_attempt(trial_user.id, submission_id, "Physics")
        
        # Verify usage record was created
        usage = db_session.query(UsageRecord).filter(
            UsageRecord.user_id == trial_user.id,
            UsageRecord.submission_id == submission_id,
        ).first()
        
        assert usage is not None
        assert usage.subject == "Physics"
        assert usage.institution_id is None
    
    def test_record_attempt_for_institution_user(
        self, db_session, institution_user, institution_with_subscription
    ):
        """Recording an attempt for institution user should include institution_id."""
        tracker = UsageTracker(db_session)
        submission_id = uuid.uuid4()
        
        tracker.record_attempt(institution_user.id, submission_id, "Chemistry")
        
        # Verify usage record was created with institution_id
        usage = db_session.query(UsageRecord).filter(
            UsageRecord.user_id == institution_user.id,
            UsageRecord.submission_id == submission_id,
        ).first()
        
        assert usage is not None
        assert usage.subject == "Chemistry"
        assert usage.institution_id == institution_with_subscription.id


class TestGetRemainingAttempts:
    """Tests for UsageTracker.get_remaining_attempts()."""
    
    def test_trial_user_remaining_attempts(self, db_session, trial_user):
        """Trial user should show remaining attempts out of 5."""
        tracker = UsageTracker(db_session)
        
        # Create 2 usage records
        for i in range(2):
            usage = UsageRecord(
                id=uuid.uuid4(),
                user_id=trial_user.id,
                submission_id=uuid.uuid4(),
                subject="Physics",
                billing_period_start=datetime.utcnow(),
            )
            db_session.add(usage)
        db_session.commit()
        
        result = tracker.get_remaining_attempts(trial_user.id)
        
        assert result.total_attempts == 2
        assert result.max_attempts == 5
        assert result.remaining_attempts == 3
        assert result.is_unlimited is False
    
    def test_pro_user_unlimited(self, db_session, pro_user):
        """Pro user should show unlimited attempts."""
        tracker = UsageTracker(db_session)
        
        result = tracker.get_remaining_attempts(pro_user.id)
        
        assert result.max_attempts is None
        assert result.remaining_attempts is None
        assert result.is_unlimited is True


class TestResetPeriodCounters:
    """Tests for UsageTracker.reset_period_counters()."""
    
    def test_reset_weekly_counter(self, db_session, institution_with_subscription):
        """Resetting weekly counter should update period start."""
        tracker = UsageTracker(db_session)
        
        # Get initial subscription
        subscription = db_session.query(Subscription).filter(
            Subscription.institution_id == institution_with_subscription.id
        ).first()
        
        initial_period_start = subscription.current_period_start
        
        # Reset weekly counter
        tracker.reset_period_counters(institution_with_subscription.id, "weekly")
        
        # Verify period start was updated
        db_session.refresh(subscription)
        assert subscription.current_period_start > initial_period_start
    
    def test_reset_invalid_period(self, db_session, institution_with_subscription):
        """Resetting with invalid period should raise ValueError."""
        tracker = UsageTracker(db_session)
        
        with pytest.raises(ValueError, match="Invalid period"):
            tracker.reset_period_counters(institution_with_subscription.id, "invalid")


class TestGetUsageStats:
    """Tests for UsageTracker.get_usage_stats()."""
    
    def test_usage_stats_basic(self, db_session, trial_user, pro_user):
        """Usage stats should aggregate attempts by subject and tier."""
        tracker = UsageTracker(db_session)
        
        # Create usage records for trial user
        for i in range(3):
            usage = UsageRecord(
                id=uuid.uuid4(),
                user_id=trial_user.id,
                submission_id=uuid.uuid4(),
                subject="Physics",
                billing_period_start=datetime.utcnow(),
            )
            db_session.add(usage)
        
        # Create usage records for pro user
        for i in range(5):
            usage = UsageRecord(
                id=uuid.uuid4(),
                user_id=pro_user.id,
                submission_id=uuid.uuid4(),
                subject="Chemistry",
                billing_period_start=datetime.utcnow(),
            )
            db_session.add(usage)
        
        db_session.commit()
        
        result = tracker.get_usage_stats()
        
        assert result["total_attempts"] == 8
        assert "Physics" in result["by_subject"]
        assert "Chemistry" in result["by_subject"]
    
    def test_usage_stats_with_date_filter(self, db_session, trial_user):
        """Usage stats should filter by date range."""
        tracker = UsageTracker(db_session)
        
        # Create usage records with different dates
        old_date = datetime.utcnow() - timedelta(days=10)
        recent_date = datetime.utcnow() - timedelta(days=1)
        
        # Old usage record
        usage1 = UsageRecord(
            id=uuid.uuid4(),
            user_id=trial_user.id,
            submission_id=uuid.uuid4(),
            subject="Physics",
            recorded_at=old_date,
            billing_period_start=old_date,
        )
        db_session.add(usage1)
        
        # Recent usage record
        usage2 = UsageRecord(
            id=uuid.uuid4(),
            user_id=trial_user.id,
            submission_id=uuid.uuid4(),
            subject="Physics",
            recorded_at=recent_date,
            billing_period_start=recent_date,
        )
        db_session.add(usage2)
        
        db_session.commit()
        
        # Query with date filter (last 5 days)
        start_date = datetime.utcnow() - timedelta(days=5)
        result = tracker.get_usage_stats(start_date=start_date)
        
        # Should only include the recent record
        assert result["total_attempts"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
