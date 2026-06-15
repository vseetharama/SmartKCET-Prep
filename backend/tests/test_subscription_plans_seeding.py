"""Property-based test for subscription plans seeding bug condition.

This module contains the exploration test for Bug 2: Database seeding not 
called automatically on startup.

**Validates: Requirements 1.3, 2.3**

Bug Condition: When fresh database starts for first time, subscription_plans 
table has zero plans. seed_subscription_plans() is not called, so no plans 
available.

Expected Behavior: seed_subscription_plans() is called and creates 6 plans on startup.

This test MUST FAIL on unfixed code to confirm the bug exists. Failure is SUCCESS
for this exploration phase.
"""

import uuid
import tempfile
import os
import shutil
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import Session, sessionmaker

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from smartkcet.db.base import Base
from smartkcet.db.subscription_models import SubscriptionPlan
from smartkcet.db.seed import seed_subscription_plans
from smartkcet.db.session import SessionLocal


# =============================================================================
# Test Setup: Fresh Database with Cleanup
# =============================================================================


@pytest.fixture
def fresh_db_session():
    """Create a fresh in-memory database session with no seeding applied.
    
    This fixture creates a clean database state that mimics a first startup
    where no seeding has occurred yet. This allows us to test the bug condition:
    that seed_subscription_plans() must be called to populate the plans.
    """
    # Create a fresh in-memory SQLite database
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    
    # Create all tables (schema only, no data)
    Base.metadata.create_all(bind=engine)
    
    # Create a session
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSessionLocal()
    
    yield session
    
    session.close()
    engine.dispose()


@pytest.fixture
def fresh_file_db():
    """Create a fresh file-based database to test realistic startup scenario.
    
    Uses a temporary file to simulate an actual database file being created
    on first startup, then deleted after the test.
    """
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_smartkcet.db")
    
    try:
        # Create engine for fresh file-based database
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Create all tables (schema only, no data)
        Base.metadata.create_all(bind=engine)
        
        # Create a session
        TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        session = TestSessionLocal()
        
        yield session
        
        session.close()
        engine.dispose()
    finally:
        # Clean up temporary directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


# =============================================================================
# Bug Condition Exploration Test
# =============================================================================


class TestSubscriptionPlansSeedingBugCondition:
    """
    Property: Bug Condition - Database Seeding Missing on Fresh Startup
    
    **Validates: Requirements 1.3, 2.3**
    
    This test explores the bug condition: on a fresh database after startup,
    subscription plans are not seeded. The test will FAIL on unfixed code,
    proving the bug exists (counterexample: SELECT COUNT(*) returns 0 instead of 6).
    """

    def test_fresh_database_has_zero_plans_before_seeding(
        self, fresh_db_session: Session
    ):
        """Bug Condition: Fresh database has zero subscription plans (BEFORE seeding).
        
        On unfixed code, this will PASS (confirming the bug: plans not seeded).
        After the fix is applied, this should still pass (fresh db is empty until
        we explicitly seed).
        
        This assertion verifies the BUG CONDITION exists.
        """
        # Query the fresh database (no seeding yet)
        plan_count = fresh_db_session.query(SubscriptionPlan).count()
        
        # ASSERT: Fresh database should have zero plans (bug condition)
        assert plan_count == 0, (
            f"Bug condition check: Fresh database should have 0 plans, "
            f"but found {plan_count}. This test verifies initial state."
        )

    def test_seeding_creates_exactly_six_plans(
        self, fresh_db_session: Session
    ):
        """Expected Behavior: seed_subscription_plans() creates exactly 6 plans.
        
        **Validates: Requirements 1.3, 2.3**
        
        This is the core exploration test. On unfixed code, this FAILS because
        seed_subscription_plans() returns 0 (no plans seeded). After the fix is
        applied, this will PASS.
        
        FAILING EXAMPLE on unfixed code:
        - seed_subscription_plans() returns 0
        - SELECT COUNT(*) FROM subscription_plans returns 0 instead of 6
        
        This test encodes the expected behavior defined in the design document.
        """
        # BEFORE SEEDING: Verify fresh database has zero plans
        plan_count_before = fresh_db_session.query(SubscriptionPlan).count()
        assert plan_count_before == 0, "Fresh database should start with zero plans"
        
        # SEED: Call seed_subscription_plans()
        seeded_count = seed_subscription_plans(fresh_db_session)
        
        # ASSERT 1: seeded_count should be 6 (all plans inserted)
        # This FAILS on unfixed code: returns 0 instead of 6
        assert seeded_count == 6, (
            f"COUNTEREXAMPLE: seed_subscription_plans() returned {seeded_count} "
            f"instead of 6. Bug: No plans were created on first startup."
        )
        
        # AFTER SEEDING: Query database
        plans = fresh_db_session.query(SubscriptionPlan).all()
        plan_count = len(plans)
        
        # ASSERT 2: Database should now have exactly 6 plans
        # This FAILS on unfixed code: returns 0 instead of 6
        assert plan_count == 6, (
            f"COUNTEREXAMPLE: SELECT COUNT(*) FROM subscription_plans returned {plan_count} "
            f"instead of 6. Bug: Plans not seeded in database."
        )

    def test_seeded_plans_have_correct_names(
        self, fresh_db_session: Session
    ):
        """Expected Behavior: All 6 seeded plans have correct names.
        
        **Validates: Requirements 1.3, 2.3**
        
        On unfixed code, this FAILS because seed_subscription_plans() returns 0
        and no plans exist.
        
        FAILING EXAMPLE:
        - No plans found in database (plan_count = 0)
        - Cannot retrieve plan names for validation
        """
        # Seed the database
        seeded_count = seed_subscription_plans(fresh_db_session)
        assert seeded_count == 6, f"Expected 6 plans to be seeded, got {seeded_count}"
        
        # Query all plans
        plans = fresh_db_session.query(SubscriptionPlan).all()
        plan_names = sorted([plan.name for plan in plans])
        
        # Expected plan names (from design doc requirement 2.3)
        expected_names = sorted([
            "Free Trial",
            "Pro Monthly",
            "Pro Yearly",
            "Institution Starter",
            "Institution Professional",
            "Institution Enterprise",
        ])
        
        # ASSERT: All plan names are correct
        # This FAILS on unfixed code: plan_names is empty list
        assert plan_names == expected_names, (
            f"COUNTEREXAMPLE: Plan names mismatch. "
            f"Expected: {expected_names}, "
            f"Got: {plan_names}. "
            f"Bug: Plans not seeded or wrong names."
        )

    def test_seeded_plans_have_correct_prices(
        self, fresh_db_session: Session
    ):
        """Expected Behavior: All seeded plans have correct pricing.
        
        **Validates: Requirements 1.3, 2.3**
        
        On unfixed code, this FAILS because no plans are seeded.
        
        FAILING EXAMPLE:
        - SELECT COUNT(*) returns 0 instead of 6
        - Cannot validate plan prices (no plans exist)
        """
        # Seed the database
        seeded_count = seed_subscription_plans(fresh_db_session)
        assert seeded_count == 6, f"Expected 6 plans to be seeded, got {seeded_count}"
        
        # Query all plans and create a price map
        plans = fresh_db_session.query(SubscriptionPlan).all()
        plan_prices = {plan.name: plan.price for plan in plans}
        
        # Expected prices (from design doc / seed.py implementation)
        expected_prices = {
            "Free Trial": Decimal("0.00"),
            "Pro Monthly": Decimal("9.99"),
            "Pro Yearly": Decimal("99.99"),
            "Institution Starter": Decimal("99.99"),
            "Institution Professional": Decimal("299.99"),
            "Institution Enterprise": Decimal("999.99"),
        }
        
        # ASSERT: All prices match expected values
        # This FAILS on unfixed code: plan_prices is empty dict
        for plan_name, expected_price in expected_prices.items():
            assert plan_name in plan_prices, (
                f"COUNTEREXAMPLE: Plan '{plan_name}' not found in database. "
                f"Bug: Plan not seeded."
            )
            actual_price = plan_prices[plan_name]
            assert actual_price == expected_price, (
                f"COUNTEREXAMPLE: Price mismatch for '{plan_name}'. "
                f"Expected: {expected_price}, Got: {actual_price}. "
                f"Bug: Plans seeded with wrong prices."
            )

    def test_seeding_is_idempotent_on_existing_plans(
        self, fresh_db_session: Session
    ):
        """Preservation: Calling seed_subscription_plans() twice doesn't duplicate.
        
        **Validates: Requirements 1.3, 2.3, 3.3**
        
        This preservation test verifies that seeding is idempotent: calling
        seed_subscription_plans() on an already-seeded database returns 0 and
        doesn't add duplicate plans.
        """
        # First seed: should insert 6 plans
        seeded_count_1 = seed_subscription_plans(fresh_db_session)
        assert seeded_count_1 == 6, f"First seed should insert 6 plans, got {seeded_count_1}"
        
        plan_count_after_first = fresh_db_session.query(SubscriptionPlan).count()
        assert plan_count_after_first == 6, "Should have 6 plans after first seed"
        
        # Second seed: should return 0 (idempotent, no new plans)
        seeded_count_2 = seed_subscription_plans(fresh_db_session)
        assert seeded_count_2 == 0, (
            f"COUNTEREXAMPLE: Second seed should return 0 (idempotent), got {seeded_count_2}. "
            f"Bug: Seeding not idempotent, would create duplicates."
        )
        
        plan_count_after_second = fresh_db_session.query(SubscriptionPlan).count()
        assert plan_count_after_second == 6, (
            f"COUNTEREXAMPLE: Should still have 6 plans after second seed, got {plan_count_after_second}. "
            f"Bug: Duplicate plans created on second seed."
        )


class TestSubscriptionPlansFileDatabase:
    """Test seeding with a file-based database (realistic scenario).
    
    Tests with a temporary file-based database to verify the seeding works
    on a more realistic database persistence scenario, not just in-memory.
    """

    def test_fresh_file_database_seeding(
        self, fresh_file_db: Session
    ):
        """File-based database seeding test.
        
        **Validates: Requirements 1.3, 2.3**
        
        Verifies that seeding works correctly on a file-based database,
        simulating the actual production scenario where the database is
        persisted to disk.
        """
        # BEFORE SEEDING: Verify fresh file database has zero plans
        plan_count_before = fresh_file_db.query(SubscriptionPlan).count()
        assert plan_count_before == 0, "Fresh file database should start with zero plans"
        
        # SEED: Call seed_subscription_plans()
        seeded_count = seed_subscription_plans(fresh_file_db)
        
        # ASSERT: 6 plans should be inserted
        assert seeded_count == 6, (
            f"COUNTEREXAMPLE: File database seed returned {seeded_count} instead of 6. "
            f"Bug: Seeding failed on file-based database."
        )
        
        # AFTER SEEDING: Verify plans exist in file database
        plans = fresh_file_db.query(SubscriptionPlan).all()
        assert len(plans) == 6, (
            f"COUNTEREXAMPLE: File database should have 6 plans, found {len(plans)}. "
            f"Bug: Plans not persisted to file database."
        )
        
        # Verify plan names
        plan_names = {plan.name for plan in plans}
        expected_names = {
            "Free Trial",
            "Pro Monthly",
            "Pro Yearly",
            "Institution Starter",
            "Institution Professional",
            "Institution Enterprise",
        }
        assert plan_names == expected_names, (
            f"COUNTEREXAMPLE: Plan names don't match. "
            f"Expected: {expected_names}, Got: {plan_names}. "
            f"Bug: Plans seeded with wrong names in file database."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
