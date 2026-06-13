"""Unit tests for SubscriptionAccessControl.

Tests the access control logic for Free Trial and Pro subscription features
as specified in tasks 5.3 and 5.4.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.db.models import Base, User
from smartkcet.db.subscription_models import (
    Institution,
    Subscription,
    SubscriptionPlan,
    UsageRecord,
)
from smartkcet.subscription.access_control import (
    AccessLevel,
    SubscriptionAccessControl,
)
from smartkcet.subscription.models import BillingPeriod


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
def trial_user(db_session: Session):
    """Create a user with an active Free Trial subscription."""
    # Create trial plan
    trial_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Free Trial",
        plan_type="individual",
        billing_period="weekly",
        price=0.0,
        max_test_attempts_per_period=None,
        max_student_seats=None,
        feature_flags={},
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(trial_plan)
    
    # Create user
    user = User(
        id=uuid.uuid4(),
        email="trial@example.com",
        kcet_student_id="TRIAL001",
        display_name="Trial User",
        password_hash="hashed",
        role="student",
        student_subtype="direct_subscriber",
        created_at=datetime.utcnow(),
    )
    db_session.add(user)
    
    # Create trial subscription
    subscription = Subscription(
        id=uuid.uuid4(),
        user_id=user.id,
        plan_id=trial_plan.id,
        status="trial",
        start_date=datetime.utcnow(),
        current_period_start=datetime.utcnow(),
        trial_duration_days=7,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(subscription)
    db_session.commit()
    
    return user


@pytest.fixture
def pro_user(db_session: Session):
    """Create a user with an active Pro subscription."""
    # Create pro plan
    pro_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Pro Monthly",
        plan_type="individual",
        billing_period="monthly",
        price=29.99,
        max_test_attempts_per_period=None,
        max_student_seats=None,
        feature_flags={},
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(pro_plan)
    
    # Create user
    user = User(
        id=uuid.uuid4(),
        email="pro@example.com",
        kcet_student_id="PRO001",
        display_name="Pro User",
        password_hash="hashed",
        role="student",
        student_subtype="direct_subscriber",
        created_at=datetime.utcnow(),
    )
    db_session.add(user)
    
    # Create pro subscription
    subscription = Subscription(
        id=uuid.uuid4(),
        user_id=user.id,
        plan_id=pro_plan.id,
        status="active",
        start_date=datetime.utcnow(),
        current_period_start=datetime.utcnow(),
        next_renewal_date=datetime.utcnow() + timedelta(days=30),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(subscription)
    db_session.commit()
    
    return user


class TestExamAccess:
    """Tests for exam access control (Task 5.3, 5.4)."""
    
    def test_trial_user_can_start_exam_with_remaining_attempts(self, db_session, trial_user):
        """Trial user with < 5 attempts should be granted exam access."""
        access_control = SubscriptionAccessControl(db_session)
        
        result = access_control.check_exam_access(trial_user.id)
        
        assert result.is_granted
        assert result.remaining_attempts == 5
    
    def test_trial_user_blocked_after_5_attempts(self, db_session, trial_user):
        """Trial user with 5 attempts should be blocked and prompted to upgrade."""
        access_control = SubscriptionAccessControl(db_session)
        
        # Create 5 usage records
        for i in range(5):
            usage = UsageRecord(
                id=uuid.uuid4(),
                user_id=trial_user.id,
                submission_id=uuid.uuid4(),
                subject="Biology",
                recorded_at=datetime.utcnow(),
                billing_period_start=datetime.utcnow(),
            )
            db_session.add(usage)
        db_session.commit()
        
        result = access_control.check_exam_access(trial_user.id)
        
        assert not result.is_granted
        assert result.requires_upgrade
        assert result.remaining_attempts == 0
        assert "upgrade" in result.reason.lower() or "limit" in result.reason.lower()
    
    def test_pro_user_has_unlimited_exam_access(self, db_session, pro_user):
        """Pro user should have unlimited exam access."""
        access_control = SubscriptionAccessControl(db_session)
        
        result = access_control.check_exam_access(pro_user.id)
        
        assert result.is_granted
        assert result.remaining_attempts is None  # Unlimited


class TestAnalyticsAccess:
    """Tests for analytics access control (Task 5.3, 5.4)."""
    
    def test_trial_user_restricted_to_basic_analytics(self, db_session, trial_user):
        """Trial user should be restricted to basic analytics."""
        access_control = SubscriptionAccessControl(db_session)
        
        result = access_control.check_analytics_access(trial_user.id)
        
        assert not result.is_granted
        assert result.requires_upgrade
        assert "analytics" in result.reason.lower()
    
    def test_pro_user_has_full_analytics_access(self, db_session, pro_user):
        """Pro user should have full analytics access."""
        access_control = SubscriptionAccessControl(db_session)
        
        result = access_control.check_analytics_access(pro_user.id)
        
        assert result.is_granted
    
    def test_filter_analytics_data_for_trial_user(self, db_session, trial_user):
        """Trial user should only see basic score display."""
        access_control = SubscriptionAccessControl(db_session)
        
        full_analytics = {
            "score_pct": 75.0,
            "pass_flag": True,
            "topic_breakdown": {"Cell Biology": 80, "Genetics": 70},
            "time_taken_sec": 3600,
            "submitted_at": "2024-01-01T00:00:00",
            "subject": "Biology",
        }
        
        filtered = access_control.filter_analytics_data(full_analytics, trial_user.id)
        
        assert filtered["score_pct"] == 75.0
        assert filtered["pass_flag"] is True
        assert "topic_breakdown" not in filtered
        assert filtered["upgrade_required"] is True
    
    def test_filter_analytics_data_for_pro_user(self, db_session, pro_user):
        """Pro user should see full analytics unchanged."""
        access_control = SubscriptionAccessControl(db_session)
        
        full_analytics = {
            "score_pct": 75.0,
            "pass_flag": True,
            "topic_breakdown": {"Cell Biology": 80, "Genetics": 70},
            "time_taken_sec": 3600,
            "submitted_at": "2024-01-01T00:00:00",
            "subject": "Biology",
        }
        
        filtered = access_control.filter_analytics_data(full_analytics, pro_user.id)
        
        assert filtered == full_analytics


class TestLeaderboardAccess:
    """Tests for leaderboard access control (Task 5.3, 5.4)."""
    
    def test_trial_user_rank_hidden(self, db_session, trial_user):
        """Trial user should have rank hidden."""
        access_control = SubscriptionAccessControl(db_session)
        
        result = access_control.check_leaderboard_access(trial_user.id)
        
        assert not result.is_granted
        assert result.requires_upgrade
        assert "leaderboard" in result.reason.lower() or "rank" in result.reason.lower()
    
    def test_pro_user_can_see_rank(self, db_session, pro_user):
        """Pro user should be able to see rank."""
        access_control = SubscriptionAccessControl(db_session)
        
        result = access_control.check_leaderboard_access(pro_user.id)
        
        assert result.is_granted
    
    def test_filter_leaderboard_data_for_trial_user(self, db_session, trial_user):
        """Trial user should see hidden rank with upgrade prompt."""
        access_control = SubscriptionAccessControl(db_session)
        
        full_leaderboard = {
            "my_rank": 15,
            "total_ranked": 100,
            "top_3": [
                {"rank": 1, "display_name": "User1", "kcet_student_id": "K001", "composite_score": 95.5},
                {"rank": 2, "display_name": "User2", "kcet_student_id": "K002", "composite_score": 92.3},
                {"rank": 3, "display_name": "User3", "kcet_student_id": "K003", "composite_score": 90.1},
            ],
            "me": {"rank": 15, "composite_score": 75.0, "average_score": 72.5},
        }
        
        filtered = access_control.filter_leaderboard_data(full_leaderboard, trial_user.id)
        
        assert filtered["my_rank"] == "—"  # em-dash for hidden
        assert filtered["me"] is None
        assert filtered["upgrade_required"] is True
        assert len(filtered["top_3"]) == 3  # Top 3 still visible
    
    def test_filter_leaderboard_data_for_pro_user(self, db_session, pro_user):
        """Pro user should see full leaderboard with medal."""
        access_control = SubscriptionAccessControl(db_session)
        
        full_leaderboard = {
            "my_rank": 5,
            "total_ranked": 100,
            "top_3": [
                {"rank": 1, "display_name": "User1", "kcet_student_id": "K001", "composite_score": 95.5},
                {"rank": 2, "display_name": "User2", "kcet_student_id": "K002", "composite_score": 92.3},
                {"rank": 3, "display_name": "User3", "kcet_student_id": "K003", "composite_score": 90.1},
            ],
            "me": {"rank": 5, "composite_score": 85.0, "average_score": 82.5},
        }
        
        filtered = access_control.filter_leaderboard_data(full_leaderboard, pro_user.id)
        
        assert filtered["my_rank"] == 5
        assert filtered["me"] is not None
        assert filtered["medal"] == "gold"  # Top 10%


class TestMedalCalculation:
    """Tests for medal tier calculation (Task 5.4)."""
    
    def test_gold_medal_top_10_percent(self, db_session):
        """Rank in top 10% should get gold medal."""
        access_control = SubscriptionAccessControl(db_session)
        
        medal = access_control.calculate_medal_tier(5, 100)
        
        assert medal == "gold"
    
    def test_silver_medal_top_25_percent(self, db_session):
        """Rank in top 25% should get silver medal."""
        access_control = SubscriptionAccessControl(db_session)
        
        medal = access_control.calculate_medal_tier(15, 100)
        
        assert medal == "silver"
    
    def test_bronze_medal_top_50_percent(self, db_session):
        """Rank in top 50% should get bronze medal."""
        access_control = SubscriptionAccessControl(db_session)
        
        medal = access_control.calculate_medal_tier(35, 100)
        
        assert medal == "bronze"
    
    def test_no_medal_below_50_percent(self, db_session):
        """Rank below top 50% should get no medal."""
        access_control = SubscriptionAccessControl(db_session)
        
        medal = access_control.calculate_medal_tier(60, 100)
        
        assert medal is None


class TestRemainingAttempts:
    """Tests for remaining attempts display (Task 5.3)."""
    
    def test_trial_user_remaining_attempts(self, db_session, trial_user):
        """Trial user should see remaining attempts out of 5."""
        access_control = SubscriptionAccessControl(db_session)
        
        # Create 2 usage records
        for i in range(2):
            usage = UsageRecord(
                id=uuid.uuid4(),
                user_id=trial_user.id,
                submission_id=uuid.uuid4(),
                subject="Biology",
                recorded_at=datetime.utcnow(),
                billing_period_start=datetime.utcnow(),
            )
            db_session.add(usage)
        db_session.commit()
        
        remaining = access_control.get_remaining_attempts(trial_user.id)
        
        assert remaining["total_attempts"] == 2
        assert remaining["max_attempts"] == 5
        assert remaining["remaining_attempts"] == 3
        assert remaining["is_unlimited"] is False
    
    def test_pro_user_unlimited_attempts(self, db_session, pro_user):
        """Pro user should see unlimited attempts."""
        access_control = SubscriptionAccessControl(db_session)
        
        remaining = access_control.get_remaining_attempts(pro_user.id)
        
        assert remaining["is_unlimited"] is True
        assert remaining["max_attempts"] is None
        assert remaining["remaining_attempts"] is None
