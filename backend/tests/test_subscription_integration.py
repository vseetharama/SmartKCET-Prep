"""Integration tests for SubscriptionService using actual database.

These tests use the real database with migrations applied to verify
the subscription service implementation works correctly.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from smartkcet.db.models import User
from smartkcet.db.subscription_models import SubscriptionPlan
from smartkcet.subscription.models import BillingPeriod
from smartkcet.subscription.service import SubscriptionService


def test_activate_trial_basic():
    """Test basic trial activation functionality."""
    # Use existing database
    engine = create_engine("sqlite:///smartkcet.db")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # Create a test user
        user_id = uuid.uuid4()
        user = session.query(User).filter(User.role == "student").first()
        
        if not user:
            print("No student user found in database. Skipping test.")
            return
        
        # Create subscription service
        service = SubscriptionService(session)
        
        # Activate trial
        subscription = service.activate_trial(user.id, duration_days=7)
        
        # Verify subscription was created
        assert subscription is not None
        assert subscription.user_id == user.id
        assert subscription.status == "trial"
        assert subscription.trial_duration_days == 7
        
        print(f"✓ Trial subscription created successfully: {subscription.id}")
        
        # Test idempotency
        subscription2 = service.activate_trial(user.id, duration_days=14)
        assert subscription.id == subscription2.id
        print(f"✓ Idempotency verified: same subscription returned")
        
    finally:
        session.close()


def test_activate_pro_basic():
    """Test basic Pro activation functionality."""
    engine = create_engine("sqlite:///smartkcet.db")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # Find a user without active subscription
        users = session.query(User).filter(User.role == "student").limit(5).all()
        
        test_user = None
        for user in users:
            # Check if user has active subscription
            from smartkcet.db.subscription_models import Subscription
            existing = session.query(Subscription).filter(
                Subscription.user_id == user.id,
                Subscription.status.in_(["trial", "active", "overdue", "grace_period"])
            ).first()
            
            if not existing:
                test_user = user
                break
        
        if not test_user:
            print("No user without active subscription found. Skipping test.")
            return
        
        # Create subscription service
        service = SubscriptionService(session)
        
        # Activate Pro weekly
        subscription = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        # Verify subscription was created
        assert subscription is not None
        assert subscription.user_id == test_user.id
        assert subscription.status == "active"
        assert subscription.next_renewal_date is not None
        
        # Verify renewal date is 7 days from start
        expected_renewal = subscription.start_date + timedelta(days=7)
        time_diff = abs((subscription.next_renewal_date - expected_renewal).total_seconds())
        assert time_diff < 2  # Allow 2 seconds tolerance
        
        print(f"✓ Pro subscription created successfully: {subscription.id}")
        print(f"✓ Renewal date correctly set to {subscription.next_renewal_date}")
        
    finally:
        session.close()


def test_get_effective_status_basic():
    """Test get_effective_status functionality."""
    engine = create_engine("sqlite:///smartkcet.db")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # Find a user with a subscription
        from smartkcet.db.subscription_models import Subscription
        subscription = session.query(Subscription).filter(
            Subscription.status.in_(["trial", "active"])
        ).first()
        
        if not subscription or not subscription.user_id:
            print("No active subscription found. Skipping test.")
            return
        
        # Create subscription service
        service = SubscriptionService(session)
        
        # Get effective status
        status = service.get_effective_status(subscription.user_id)
        
        # Verify status
        assert status.has_subscription is True
        assert status.is_active is True
        assert status.status in ["trial", "active"]
        
        print(f"✓ Effective status retrieved successfully")
        print(f"  - Has subscription: {status.has_subscription}")
        print(f"  - Status: {status.status}")
        print(f"  - Is active: {status.is_active}")
        print(f"  - Is trial: {status.is_trial}")
        
        if status.is_trial:
            print(f"  - Trial attempts remaining: {status.trial_attempts_remaining}")
        else:
            print(f"  - Next renewal: {status.next_renewal_date}")
        
    finally:
        session.close()


if __name__ == "__main__":
    print("Running subscription service integration tests...\n")
    
    print("Test 1: activate_trial")
    test_activate_trial_basic()
    print()
    
    print("Test 2: activate_pro")
    test_activate_pro_basic()
    print()
    
    print("Test 3: get_effective_status")
    test_get_effective_status_basic()
    print()
    
    print("All tests completed!")
