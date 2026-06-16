"""Test subscription upgrade rules for all 5 user scenarios.

Tests the business rules:
1. Free User: Can upgrade to any paid plan
2. Trial User: Cannot switch until expiry
3. Monthly User: Cannot switch until expiry
4. Yearly User: Cannot switch until expiry
5. Expired User: Can choose any plan again
"""

import uuid
from datetime import datetime, timedelta
from uuid import uuid4

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
from smartkcet.subscription.service import SubscriptionService


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    session.close()


class TestSubscriptionUpgradeRules:
    """Test all subscription upgrade scenarios"""

    @pytest.fixture
    def subscription_service(self, db_session: Session):
        """Create a subscription service instance"""
        return SubscriptionService(db_session)

    @pytest.fixture
    def test_user_id(self, db_session: Session):
        """Create and return a test user ID"""
        user = User(
            id=uuid4(),
            email="testuser@example.com",
            display_name="Test User",
            password_hash="hash",
            role="student",
            kcet_student_id="TEST001"
        )
        db_session.add(user)
        db_session.commit()
        return user.id

    @pytest.fixture
    def free_plan(self, db_session: Session):
        """Create the Free plan"""
        plan = SubscriptionPlan(
            id=str(uuid4()),
            name="Free",
            price=0,
            plan_type="individual",
            billing_period="weekly",  # Must be weekly or monthly per DB constraints
            is_active=True
        )
        db_session.add(plan)
        db_session.commit()
        return plan

    @pytest.fixture
    def trial_plan(self, db_session: Session):
        """Create the Trial plan"""
        plan = SubscriptionPlan(
            id=str(uuid4()),
            name="Free Trial",
            price=99,
            plan_type="individual",
            billing_period="weekly",
            is_active=True
        )
        db_session.add(plan)
        db_session.commit()
        return plan

    @pytest.fixture
    def monthly_plan(self, db_session: Session):
        """Create the Monthly plan"""
        plan = SubscriptionPlan(
            id=str(uuid4()),
            name="Pro Monthly",
            price=349,
            plan_type="individual",
            billing_period="monthly",
            is_active=True
        )
        db_session.add(plan)
        db_session.commit()
        return plan

    @pytest.fixture
    def yearly_plan(self, db_session: Session):
        """Create the Yearly plan (uses monthly billing period in DB)"""
        plan = SubscriptionPlan(
            id=str(uuid4()),
            name="Pro Yearly",
            price=2999,
            plan_type="individual",
            billing_period="monthly",  # DB only allows weekly or monthly
            is_active=True
        )
        db_session.add(plan)
        db_session.commit()
        return plan

    def test_free_user_can_upgrade_to_trial(self, db_session: Session, subscription_service, test_user_id, free_plan, trial_plan):
        """Scenario 1: Free user can upgrade to Trial plan"""
        now = datetime.utcnow()
        
        # Create Free subscription
        free_sub = Subscription(
            id=uuid4(),
            user_id=test_user_id,
            plan_id=free_plan.id,
            status="active",
            start_date=now,
            current_period_start=now,
            next_renewal_date=None  # Free doesn't renew
        )
        db_session.add(free_sub)
        db_session.commit()
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is True, "Free user should be able to upgrade"
        assert error_msg is None

    def test_free_user_can_upgrade_to_monthly(self, db_session: Session, subscription_service, test_user_id, free_plan, monthly_plan):
        """Scenario 1: Free user can upgrade to Monthly plan"""
        now = datetime.utcnow()
        
        # Create Free subscription
        free_sub = Subscription(
            id=uuid4(),
            user_id=test_user_id,
            plan_id=free_plan.id,
            status="active",
            start_date=now,
            current_period_start=now,
            next_renewal_date=None
        )
        db_session.add(free_sub)
        db_session.commit()
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is True, "Free user should be able to upgrade to Monthly"
        assert error_msg is None

    def test_free_user_can_upgrade_to_yearly(self, db_session: Session, subscription_service, test_user_id, free_plan, yearly_plan):
        """Scenario 1: Free user can upgrade to Yearly plan"""
        now = datetime.utcnow()
        
        # Create Free subscription
        free_sub = Subscription(
            id=uuid4(),
            user_id=test_user_id,
            plan_id=free_plan.id,
            status="active",
            start_date=now,
            current_period_start=now,
            next_renewal_date=None
        )
        db_session.add(free_sub)
        db_session.commit()
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is True, "Free user should be able to upgrade to Yearly"
        assert error_msg is None

    def test_trial_user_cannot_switch_to_monthly(self, db_session: Session, subscription_service, test_user_id, trial_plan):
        """Scenario 2: Trial user cannot switch to Monthly"""
        now = datetime.utcnow()
        
        # Create Trial subscription (active)
        trial_sub = Subscription(
            id=uuid4(),
            user_id=test_user_id,
            plan_id=trial_plan.id,
            status="trial",
            start_date=now,
            current_period_start=now,
            next_renewal_date=now + timedelta(days=7)
        )
        db_session.add(trial_sub)
        db_session.commit()
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is False, "Trial user should NOT be able to switch plans"
        assert error_msg is not None
        assert "days" in error_msg or "expiry" in error_msg.lower()

    def test_trial_user_cannot_go_back_to_free(self, db_session: Session, subscription_service, test_user_id, trial_plan):
        """Scenario 2: Trial user cannot go back to Free"""
        now = datetime.utcnow()
        
        # Create Trial subscription (active)
        trial_sub = Subscription(
            id=uuid4(),
            user_id=test_user_id,
            plan_id=trial_plan.id,
            status="trial",
            start_date=now,
            current_period_start=now,
            next_renewal_date=now + timedelta(days=7)
        )
        db_session.add(trial_sub)
        db_session.commit()
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is False, "Trial user should NOT be able to downgrade to Free"
        assert error_msg is not None

    def test_monthly_user_cannot_switch_to_yearly(self, db_session: Session, subscription_service, test_user_id, monthly_plan):
        """Scenario 3: Monthly user cannot switch to Yearly"""
        now = datetime.utcnow()
        
        # Create Monthly subscription (active)
        monthly_sub = Subscription(
            id=uuid4(),
            user_id=test_user_id,
            plan_id=monthly_plan.id,
            status="active",
            start_date=now,
            current_period_start=now,
            next_renewal_date=now + timedelta(days=30)
        )
        db_session.add(monthly_sub)
        db_session.commit()
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is False, "Monthly user should NOT be able to switch plans"
        assert error_msg is not None
        assert "days" in error_msg or "expiry" in error_msg.lower()

    def test_yearly_user_cannot_buy_any_other_plan(self, db_session: Session, subscription_service, test_user_id, yearly_plan):
        """Scenario 4: Yearly user cannot buy any other plan"""
        now = datetime.utcnow()
        
        # Create Yearly subscription (active)
        yearly_sub = Subscription(
            id=uuid4(),
            user_id=test_user_id,
            plan_id=yearly_plan.id,
            status="active",
            start_date=now,
            current_period_start=now,
            next_renewal_date=now + timedelta(days=365)
        )
        db_session.add(yearly_sub)
        db_session.commit()
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is False, "Yearly user should NOT be able to buy any other plan"
        assert error_msg is not None
        assert "days" in error_msg and "expiry" not in error_msg.lower(), f"Error message should mention days: {error_msg}"

    def test_expired_user_can_choose_any_plan(self, db_session: Session, subscription_service, test_user_id, trial_plan):
        """Scenario 5: Expired user can choose any plan"""
        # Don't create any active subscription - simulate expired state
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is True, "Expired/no subscription user should be able to choose any plan"
        assert error_msg is None

    def test_expired_subscription_state(self, db_session: Session, subscription_service, test_user_id, trial_plan):
        """Scenario 5: User with expired subscription (status='expired') can choose any plan"""
        now = datetime.utcnow()
        
        # Create Trial subscription with expired status
        trial_sub = Subscription(
            id=uuid4(),
            user_id=test_user_id,
            plan_id=trial_plan.id,
            status="expired",
            start_date=now - timedelta(days=10),
            current_period_start=now - timedelta(days=10),
            next_renewal_date=now - timedelta(days=3)
        )
        db_session.add(trial_sub)
        db_session.commit()
        
        # Check if user can change subscription
        can_change, error_msg = subscription_service.can_change_subscription(test_user_id)
        
        assert can_change is True, "User with expired subscription should be able to choose any plan"
        assert error_msg is None
