"""Manual test for activate_pro functionality."""

import uuid
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from smartkcet.db.models import User
from smartkcet.subscription.models import BillingPeriod
from smartkcet.subscription.service import SubscriptionService


def test_activate_pro():
    """Test Pro subscription activation."""
    engine = create_engine("sqlite:///smartkcet.db")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # Create a new test user
        test_user = User(
            id=uuid.uuid4(),
            email=f"test_pro_{uuid.uuid4().hex[:8]}@example.com",
            kcet_student_id=f"TEST_PRO_{uuid.uuid4().hex[:8]}",
            display_name="Test Pro User",
            password_hash="hashed_password",
            role="student",
            student_subtype="direct_subscriber",
        )
        session.add(test_user)
        session.commit()
        
        print(f"Created test user: {test_user.email}")
        
        # Create subscription service
        service = SubscriptionService(session)
        
        # Test Weekly Pro subscription
        print("\nTesting Weekly Pro subscription...")
        subscription_weekly = service.activate_pro(test_user.id, BillingPeriod.WEEKLY)
        
        assert subscription_weekly is not None
        assert subscription_weekly.user_id == test_user.id
        assert subscription_weekly.status == "active"
        assert subscription_weekly.next_renewal_date is not None
        
        # Verify renewal date is 7 days from start
        expected_renewal = subscription_weekly.start_date + timedelta(days=7)
        time_diff = abs((subscription_weekly.next_renewal_date - expected_renewal).total_seconds())
        assert time_diff < 2, f"Renewal date mismatch: expected {expected_renewal}, got {subscription_weekly.next_renewal_date}"
        
        print(f"✓ Weekly Pro subscription created: {subscription_weekly.id}")
        print(f"✓ Start date: {subscription_weekly.start_date}")
        print(f"✓ Next renewal: {subscription_weekly.next_renewal_date}")
        print(f"✓ Renewal date correctly set (7 days from start)")
        
        # Test idempotency
        print("\nTesting idempotency...")
        subscription_weekly2 = service.activate_pro(test_user.id, BillingPeriod.MONTHLY)
        assert subscription_weekly.id == subscription_weekly2.id
        print(f"✓ Idempotency verified: same subscription returned")
        
        # Clean up
        from smartkcet.db.subscription_models import Subscription
        session.query(Subscription).filter(Subscription.user_id == test_user.id).delete()
        session.delete(test_user)
        session.commit()
        print(f"\n✓ Test user cleaned up")
        
        # Test Monthly Pro subscription with a new user
        print("\n" + "="*60)
        print("Testing Monthly Pro subscription...")
        test_user2 = User(
            id=uuid.uuid4(),
            email=f"test_pro_monthly_{uuid.uuid4().hex[:8]}@example.com",
            kcet_student_id=f"TEST_PRO_M_{uuid.uuid4().hex[:8]}",
            display_name="Test Pro Monthly User",
            password_hash="hashed_password",
            role="student",
            student_subtype="direct_subscriber",
        )
        session.add(test_user2)
        session.commit()
        
        print(f"Created test user: {test_user2.email}")
        
        subscription_monthly = service.activate_pro(test_user2.id, BillingPeriod.MONTHLY)
        
        assert subscription_monthly is not None
        assert subscription_monthly.user_id == test_user2.id
        assert subscription_monthly.status == "active"
        assert subscription_monthly.next_renewal_date is not None
        
        # Verify renewal date is 30 days from start
        expected_renewal = subscription_monthly.start_date + timedelta(days=30)
        time_diff = abs((subscription_monthly.next_renewal_date - expected_renewal).total_seconds())
        assert time_diff < 2, f"Renewal date mismatch: expected {expected_renewal}, got {subscription_monthly.next_renewal_date}"
        
        print(f"✓ Monthly Pro subscription created: {subscription_monthly.id}")
        print(f"✓ Start date: {subscription_monthly.start_date}")
        print(f"✓ Next renewal: {subscription_monthly.next_renewal_date}")
        print(f"✓ Renewal date correctly set (30 days from start)")
        
        # Clean up
        session.query(Subscription).filter(Subscription.user_id == test_user2.id).delete()
        session.delete(test_user2)
        session.commit()
        print(f"\n✓ Test user cleaned up")
        
        print("\n" + "="*60)
        print("All activate_pro tests passed! ✓")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    test_activate_pro()
