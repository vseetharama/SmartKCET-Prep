"""Seed Pro subscription plans into the database."""

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from smartkcet.db.subscription_models import SubscriptionPlan


def seed_pro_plans():
    """Create Pro Weekly and Pro Monthly plans."""
    engine = create_engine("sqlite:///smartkcet.db")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # Check if Pro plans already exist
        existing_weekly = session.query(SubscriptionPlan).filter(
            SubscriptionPlan.name == "Pro Weekly",
            SubscriptionPlan.plan_type == "individual"
        ).first()
        
        existing_monthly = session.query(SubscriptionPlan).filter(
            SubscriptionPlan.name == "Pro Monthly",
            SubscriptionPlan.plan_type == "individual"
        ).first()
        
        if existing_weekly and existing_monthly:
            print("Pro plans already exist. Skipping.")
            return
        
        # Create Pro Weekly plan
        if not existing_weekly:
            pro_weekly = SubscriptionPlan(
                id=uuid.uuid4(),
                name="Pro Weekly",
                plan_type="individual",
                billing_period="weekly",
                price=99.0,
                max_test_attempts_per_period=None,  # Unlimited
                is_active=True,
            )
            session.add(pro_weekly)
            print(f"✓ Created Pro Weekly plan: {pro_weekly.id}")
        
        # Create Pro Monthly plan
        if not existing_monthly:
            pro_monthly = SubscriptionPlan(
                id=uuid.uuid4(),
                name="Pro Monthly",
                plan_type="individual",
                billing_period="monthly",
                price=299.0,
                max_test_attempts_per_period=None,  # Unlimited
                is_active=True,
            )
            session.add(pro_monthly)
            print(f"✓ Created Pro Monthly plan: {pro_monthly.id}")
        
        session.commit()
        print("\n✓ Pro plans seeded successfully!")
        
        # List all plans
        plans = session.query(SubscriptionPlan).all()
        print("\nAll subscription plans:")
        for plan in plans:
            print(f"  - {plan.name} ({plan.plan_type}, {plan.billing_period}, ${plan.price})")
        
    except Exception as e:
        print(f"✗ Error seeding plans: {e}")
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    seed_pro_plans()
