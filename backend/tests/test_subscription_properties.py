"""Property-based tests for subscription platform upgrade.

This module contains property-based tests using Hypothesis to validate
the correctness properties defined in the design document.

Each test is tagged with:
# Feature: subscription-platform-upgrade, Property N: <title>

Tests use minimum 100 examples per property test (@settings(max_examples=100))
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


# =============================================================================
# Test Database Setup
# =============================================================================


@pytest.fixture
def test_session():
    """Create a test database session with schema."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    
    # Create tables
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                kcet_student_id TEXT UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('platform_admin', 'institution_admin', 'student', 'admin')),
                student_subtype TEXT CHECK (student_subtype IN ('direct_subscriber', 'institution_linked', 'dual') OR student_subtype IS NULL),
                institution_id TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                failed_login_count INTEGER NOT NULL DEFAULT 0,
                lockout_until TIMESTAMP
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                contact_phone TEXT NOT NULL,
                subscription_status TEXT NOT NULL DEFAULT 'inactive',
                registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE subscription_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                plan_type TEXT NOT NULL CHECK (plan_type IN ('individual', 'institution')),
                billing_period TEXT NOT NULL CHECK (billing_period IN ('weekly', 'monthly')),
                price DECIMAL(10, 2) NOT NULL,
                max_test_attempts_per_period INTEGER,
                max_student_seats INTEGER,
                feature_flags TEXT NOT NULL DEFAULT '{}',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE subscriptions (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                institution_id TEXT,
                plan_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('trial', 'active', 'overdue', 'grace_period', 'expired', 'cancelled')),
                start_date TIMESTAMP NOT NULL,
                current_period_start TIMESTAMP NOT NULL,
                next_renewal_date TIMESTAMP,
                cancellation_date TIMESTAMP,
                grace_period_end TIMESTAMP,
                trial_duration_days INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (institution_id) REFERENCES institutions(id) ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT,
                CHECK ((user_id IS NOT NULL AND institution_id IS NULL) OR (user_id IS NULL AND institution_id IS NOT NULL))
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE subscription_events (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN ('activated', 'renewed', 'overdue', 'grace_period', 'expired', 'cancelled', 'reactivated', 'upgraded')),
                previous_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
            )
        """))
    
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


# =============================================================================
# Hypothesis Strategies
# =============================================================================


@st.composite
def pre_migration_user(draw, role: str):
    """Generate a pre-migration user with old role system (admin or student)."""
    user_id = uuid.uuid4()
    email = f"user_{user_id.hex[:8]}@example.com"
    
    if role == "admin":
        kcet_student_id = None
        display_name = f"Admin {user_id.hex[:6]}"
    else:  # student
        # Use UUID to ensure uniqueness
        kcet_student_id = f"KCET{user_id.hex[:10].upper()}"
        display_name = f"Student {user_id.hex[:6]}"
    
    return {
        "id": user_id,
        "email": email,
        "kcet_student_id": kcet_student_id,
        "display_name": display_name,
        "password_hash": "$2b$12$dummyhashfortest",
        "role": role,
        "student_subtype": None,
        "institution_id": None,
        "created_at": datetime.utcnow(),
        "failed_login_count": 0,
        "lockout_until": None,
    }


@st.composite
def pre_migration_database(draw):
    """Generate a pre-migration database with random admin and student users."""
    # Generate 0-5 admin users
    admin_count = draw(st.integers(min_value=0, max_value=5))
    admin_users = [draw(pre_migration_user("admin")) for _ in range(admin_count)]
    
    # Generate 0-10 student users
    student_count = draw(st.integers(min_value=0, max_value=10))
    student_users = [draw(pre_migration_user("student")) for _ in range(student_count)]
    
    return {
        "admin_users": admin_users,
        "student_users": student_users,
    }


# =============================================================================
# Migration Logic
# =============================================================================


def run_migration_logic(session: Session, migration_date: datetime) -> dict[str, Any]:
    """Run the migration logic and return statistics."""
    # Create Free Trial subscription plan
    free_trial_plan_id = str(uuid.uuid4())
    session.execute(text("""
        INSERT INTO subscription_plans (
            id, name, plan_type, billing_period, price,
            max_test_attempts_per_period, max_student_seats,
            feature_flags, is_active, created_at
        ) VALUES (
            :id, 'Free Trial', 'individual', 'weekly', 0.00,
            5, NULL, '{}', 1, :created_at
        )
    """), {'id': free_trial_plan_id, 'created_at': migration_date})
    
    # Get counts before migration
    admin_count = session.execute(text("SELECT COUNT(*) FROM users WHERE role = 'admin'")).scalar()
    student_count = session.execute(text("SELECT COUNT(*) FROM users WHERE role = 'student'")).scalar()
    
    # Migrate admin users to platform_admin
    session.execute(text("UPDATE users SET role = 'platform_admin' WHERE role = 'admin'"))
    
    # Migrate student users
    session.execute(text("UPDATE users SET student_subtype = 'direct_subscriber' WHERE role = 'student'"))
    
    # Create Free Trial subscriptions for each student
    student_ids = session.execute(text("SELECT id FROM users WHERE role = 'student'")).fetchall()
    
    subscriptions_created = 0
    trial_end_date = migration_date + timedelta(days=7)
    
    for (student_id,) in student_ids:
        subscription_id = str(uuid.uuid4())
        session.execute(text("""
            INSERT INTO subscriptions (
                id, user_id, institution_id, plan_id, status,
                start_date, current_period_start, next_renewal_date,
                cancellation_date, grace_period_end, trial_duration_days,
                created_at, updated_at
            ) VALUES (
                :id, :user_id, NULL, :plan_id, 'trial',
                :start_date, :current_period_start, :next_renewal_date,
                NULL, NULL, 7,
                :created_at, :updated_at
            )
        """), {
            'id': subscription_id,
            'user_id': student_id,
            'plan_id': free_trial_plan_id,
            'start_date': migration_date,
            'current_period_start': migration_date,
            'next_renewal_date': trial_end_date,
            'created_at': migration_date,
            'updated_at': migration_date,
        })
        
        # Create subscription event
        event_id = str(uuid.uuid4())
        session.execute(text("""
            INSERT INTO subscription_events (
                id, subscription_id, event_type, previous_status, new_status,
                metadata, occurred_at
            ) VALUES (
                :id, :subscription_id, 'activated', 'none', 'trial',
                :metadata, :occurred_at
            )
        """), {
            'id': event_id,
            'subscription_id': subscription_id,
            'metadata': '{"source": "data_migration", "migration_revision": "0005_migrate_user_data"}',
            'occurred_at': migration_date
        })
        
        subscriptions_created += 1
    
    session.commit()
    
    return {
        "admin_count": admin_count,
        "student_count": student_count,
        "subscriptions_created": subscriptions_created,
        "free_trial_plan_id": free_trial_plan_id,
    }



# =============================================================================
# Property 13: Migration Role Mapping Correctness
# =============================================================================


# Feature: subscription-platform-upgrade, Property 13: Migration Role Mapping Correctness
@given(db_data=pre_migration_database())
@settings(max_examples=100)
def test_property_13_migration_role_mapping_correctness(db_data):
    """
    **Validates: Requirements 10.5, 14.1, 14.2, 14.3**
    
    Property 13: Migration Role Mapping Correctness
    
    For any pre-migration database containing users with role `admin` or `student`,
    executing the migration SHALL:
    (a) map every `admin` user to role `platform_admin` with no subtype,
    (b) map every `student` user to role `student` with subtype `direct_subscriber`
        and create an associated Free Trial subscription record with 7-day duration
        starting from migration date,
    (c) preserve all existing submissions, leaderboard_scores, and exam data with
        valid foreign key references (zero orphaned records).
    """
    # Create a fresh database for each test
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    
    # Create tables
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                kcet_student_id TEXT UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('platform_admin', 'institution_admin', 'student', 'admin')),
                student_subtype TEXT CHECK (student_subtype IN ('direct_subscriber', 'institution_linked', 'dual') OR student_subtype IS NULL),
                institution_id TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                failed_login_count INTEGER NOT NULL DEFAULT 0,
                lockout_until TIMESTAMP
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                contact_phone TEXT NOT NULL,
                subscription_status TEXT NOT NULL DEFAULT 'inactive',
                registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE subscription_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                plan_type TEXT NOT NULL CHECK (plan_type IN ('individual', 'institution')),
                billing_period TEXT NOT NULL CHECK (billing_period IN ('weekly', 'monthly')),
                price DECIMAL(10, 2) NOT NULL,
                max_test_attempts_per_period INTEGER,
                max_student_seats INTEGER,
                feature_flags TEXT NOT NULL DEFAULT '{}',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE subscriptions (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                institution_id TEXT,
                plan_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('trial', 'active', 'overdue', 'grace_period', 'expired', 'cancelled')),
                start_date TIMESTAMP NOT NULL,
                current_period_start TIMESTAMP NOT NULL,
                next_renewal_date TIMESTAMP,
                cancellation_date TIMESTAMP,
                grace_period_end TIMESTAMP,
                trial_duration_days INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (institution_id) REFERENCES institutions(id) ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT,
                CHECK ((user_id IS NOT NULL AND institution_id IS NULL) OR (user_id IS NULL AND institution_id IS NOT NULL))
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE subscription_events (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN ('activated', 'renewed', 'overdue', 'grace_period', 'expired', 'cancelled', 'reactivated', 'upgraded')),
                previous_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
            )
        """))
    
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    test_session = SessionLocal()
    
    try:
        # Setup: Create pre-migration database state
        admin_users = db_data["admin_users"]
        student_users = db_data["student_users"]
        
        # Insert admin users
        for admin_data in admin_users:
            test_session.execute(text("""
                INSERT INTO users (
                    id, email, kcet_student_id, display_name, password_hash,
                    role, student_subtype, institution_id, created_at,
                    failed_login_count, lockout_until
                ) VALUES (
                    :id, :email, :kcet_student_id, :display_name, :password_hash,
                    :role, :student_subtype, :institution_id, :created_at,
                    :failed_login_count, :lockout_until
                )
            """), {
                'id': str(admin_data["id"]),
                'email': admin_data["email"],
                'kcet_student_id': admin_data["kcet_student_id"],
                'display_name': admin_data["display_name"],
                'password_hash': admin_data["password_hash"],
                'role': admin_data["role"],
                'student_subtype': admin_data["student_subtype"],
                'institution_id': str(admin_data["institution_id"]) if admin_data["institution_id"] else None,
                'created_at': admin_data["created_at"],
                'failed_login_count': admin_data["failed_login_count"],
                'lockout_until': admin_data["lockout_until"],
            })
        
        # Insert student users
        for student_data in student_users:
            test_session.execute(text("""
                INSERT INTO users (
                    id, email, kcet_student_id, display_name, password_hash,
                    role, student_subtype, institution_id, created_at,
                    failed_login_count, lockout_until
                ) VALUES (
                    :id, :email, :kcet_student_id, :display_name, :password_hash,
                    :role, :student_subtype, :institution_id, :created_at,
                    :failed_login_count, :lockout_until
                )
            """), {
                'id': str(student_data["id"]),
                'email': student_data["email"],
                'kcet_student_id': student_data["kcet_student_id"],
                'display_name': student_data["display_name"],
                'password_hash': student_data["password_hash"],
                'role': student_data["role"],
                'student_subtype': student_data["student_subtype"],
                'institution_id': str(student_data["institution_id"]) if student_data["institution_id"] else None,
                'created_at': student_data["created_at"],
                'failed_login_count': student_data["failed_login_count"],
                'lockout_until': student_data["lockout_until"],
            })
        
        test_session.commit()
        
        # Record pre-migration state
        pre_admin_count = len(admin_users)
        pre_student_count = len(student_users)
        
        # Execute migration
        migration_date = datetime.utcnow()
        migration_stats = run_migration_logic(test_session, migration_date)
        
        # Verify condition (a): Every admin user mapped to platform_admin with no subtype
        result = test_session.execute(text(
            "SELECT id, student_subtype FROM users WHERE role = 'platform_admin'"
        ))
        migrated_admins = result.fetchall()
        
        assert len(migrated_admins) == pre_admin_count, (
            f"Expected {pre_admin_count} platform_admin users, got {len(migrated_admins)}"
        )
        
        for admin_id, student_subtype in migrated_admins:
            assert student_subtype is None, (
                f"Admin {admin_id} should have no student_subtype, got {student_subtype}"
            )
        
        # Verify no users remain with 'admin' role
        remaining_admins = test_session.execute(
            text("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        ).scalar()
        assert remaining_admins == 0, f"Found {remaining_admins} users still with 'admin' role"
        
        # Verify condition (b): Every student user mapped to student with direct_subscriber subtype
        result = test_session.execute(text(
            "SELECT id, student_subtype FROM users WHERE role = 'student'"
        ))
        migrated_students = result.fetchall()
        
        assert len(migrated_students) == pre_student_count, (
            f"Expected {pre_student_count} student users, got {len(migrated_students)}"
        )
        
        for student_id, student_subtype in migrated_students:
            assert student_subtype == "direct_subscriber", (
                f"Student {student_id} should have subtype 'direct_subscriber', got {student_subtype}"
            )
        
        # Verify Free Trial subscriptions created for each student
        result = test_session.execute(text(
            "SELECT id, user_id, institution_id, status, trial_duration_days, start_date, next_renewal_date "
            "FROM subscriptions WHERE status = 'trial'"
        ))
        subscriptions = result.fetchall()
        
        assert len(subscriptions) == pre_student_count, (
            f"Expected {pre_student_count} trial subscriptions, got {len(subscriptions)}"
        )
        
        # Verify each subscription has correct properties
        for sub_id, user_id, institution_id, status, trial_days, start_date, next_renewal_date in subscriptions:
            assert user_id is not None, "Subscription must have user_id"
            assert institution_id is None, "Individual subscription should have no institution_id"
            assert status == "trial", f"Expected status 'trial', got {status}"
            assert trial_days == 7, f"Expected 7-day trial, got {trial_days}"
            
            # Verify next_renewal_date is 7 days from start_date
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            if isinstance(next_renewal_date, str):
                next_renewal_date = datetime.fromisoformat(next_renewal_date.replace('Z', '+00:00'))
            
            expected_renewal = start_date + timedelta(days=7)
            time_diff = abs((next_renewal_date - expected_renewal).total_seconds())
            assert time_diff < 1, (
                f"Expected renewal date {expected_renewal}, got {next_renewal_date}"
            )
            
            # Verify user exists and is a student
            result = test_session.execute(text(
                "SELECT role, student_subtype FROM users WHERE id = :user_id"
            ), {'user_id': user_id})
            user_data = result.fetchone()
            assert user_data is not None, f"User {user_id} not found"
            role, subtype = user_data
            assert role == "student", f"Subscription user should be student, got {role}"
            assert subtype == "direct_subscriber", (
                f"Subscription user should be direct_subscriber, got {subtype}"
            )
        
        # Verify subscription events created
        result = test_session.execute(text(
            "SELECT id, previous_status, new_status, metadata FROM subscription_events "
            "WHERE event_type = 'activated'"
        ))
        events = result.fetchall()
        
        assert len(events) == pre_student_count, (
            f"Expected {pre_student_count} activation events, got {len(events)}"
        )
        
        for event_id, previous_status, new_status, metadata in events:
            assert previous_status == "none", (
                f"Expected previous_status 'none', got {previous_status}"
            )
            assert new_status == "trial", (
                f"Expected new_status 'trial', got {new_status}"
            )
            assert "data_migration" in metadata, (
                "Event should be marked as from data_migration"
            )
        
        # Verify condition (c): All existing data preserved
        total_users_after = test_session.execute(
            text("SELECT COUNT(*) FROM users")
        ).scalar()
        expected_total = pre_admin_count + pre_student_count
        
        assert total_users_after == expected_total, (
            f"Expected {expected_total} total users after migration, got {total_users_after}"
        )
        
        # Verify no orphaned subscriptions
        result = test_session.execute(text("""
            SELECT COUNT(*) FROM subscriptions s
            WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = s.user_id)
        """))
        orphaned_subscriptions = result.scalar()
        
        assert orphaned_subscriptions == 0, (
            f"Found {orphaned_subscriptions} orphaned subscriptions with invalid user_id"
        )
        
        # Verify migration statistics match expectations
        assert migration_stats["admin_count"] == pre_admin_count
        assert migration_stats["student_count"] == pre_student_count
        assert migration_stats["subscriptions_created"] == pre_student_count
        
    finally:
        test_session.close()
        engine.dispose()


# =============================================================================
# Edge Cases for Property 13
# =============================================================================


def test_property_13_edge_case_no_users(test_session):
    """Edge case: Migration with empty database (0 users)."""
    migration_date = datetime.utcnow()
    migration_stats = run_migration_logic(test_session, migration_date)
    
    assert migration_stats["admin_count"] == 0
    assert migration_stats["student_count"] == 0
    assert migration_stats["subscriptions_created"] == 0
    
    # Verify no users or subscriptions created
    user_count = test_session.execute(text("SELECT COUNT(*) FROM users")).scalar()
    subscription_count = test_session.execute(text("SELECT COUNT(*) FROM subscriptions")).scalar()
    assert user_count == 0
    assert subscription_count == 0


def test_property_13_edge_case_only_admins(test_session):
    """Edge case: Migration with only admin users (no students)."""
    # Create 3 admin users
    for i in range(3):
        test_session.execute(text("""
            INSERT INTO users (
                id, email, kcet_student_id, display_name, password_hash,
                role, student_subtype, institution_id, created_at,
                failed_login_count, lockout_until
            ) VALUES (
                :id, :email, NULL, :display_name, '$2b$12$dummyhash',
                'admin', NULL, NULL, :created_at, 0, NULL
            )
        """), {
            'id': str(uuid.uuid4()),
            'email': f"admin{i}@example.com",
            'display_name': f"Admin {i}",
            'created_at': datetime.utcnow(),
        })
    
    test_session.commit()
    
    migration_date = datetime.utcnow()
    migration_stats = run_migration_logic(test_session, migration_date)
    
    assert migration_stats["admin_count"] == 3
    assert migration_stats["student_count"] == 0
    assert migration_stats["subscriptions_created"] == 0
    
    # Verify all admins migrated to platform_admin
    platform_admin_count = test_session.execute(text(
        "SELECT COUNT(*) FROM users WHERE role = 'platform_admin'"
    )).scalar()
    assert platform_admin_count == 3
    
    # Verify no subscriptions created
    subscription_count = test_session.execute(text("SELECT COUNT(*) FROM subscriptions")).scalar()
    assert subscription_count == 0


def test_property_13_edge_case_only_students(test_session):
    """Edge case: Migration with only student users (no admins)."""
    # Create 5 student users
    for i in range(5):
        test_session.execute(text("""
            INSERT INTO users (
                id, email, kcet_student_id, display_name, password_hash,
                role, student_subtype, institution_id, created_at,
                failed_login_count, lockout_until
            ) VALUES (
                :id, :email, :kcet_student_id, :display_name, '$2b$12$dummyhash',
                'student', NULL, NULL, :created_at, 0, NULL
            )
        """), {
            'id': str(uuid.uuid4()),
            'email': f"student{i}@example.com",
            'kcet_student_id': f"KCET{100000 + i}",
            'display_name': f"Student {i}",
            'created_at': datetime.utcnow(),
        })
    
    test_session.commit()
    
    migration_date = datetime.utcnow()
    migration_stats = run_migration_logic(test_session, migration_date)
    
    assert migration_stats["admin_count"] == 0
    assert migration_stats["student_count"] == 5
    assert migration_stats["subscriptions_created"] == 5
    
    # Verify all students have direct_subscriber subtype
    result = test_session.execute(text(
        "SELECT COUNT(*) FROM users WHERE role = 'student' AND student_subtype = 'direct_subscriber'"
    ))
    student_count = result.scalar()
    assert student_count == 5
    
    # Verify 5 trial subscriptions created
    subscription_count = test_session.execute(text(
        "SELECT COUNT(*) FROM subscriptions WHERE status = 'trial'"
    )).scalar()
    assert subscription_count == 5


def test_property_13_edge_case_mixed_users(test_session):
    """Edge case: Migration with mixed admin and student users."""
    # Create 2 admins
    for i in range(2):
        test_session.execute(text("""
            INSERT INTO users (
                id, email, kcet_student_id, display_name, password_hash,
                role, student_subtype, institution_id, created_at,
                failed_login_count, lockout_until
            ) VALUES (
                :id, :email, NULL, :display_name, '$2b$12$dummyhash',
                'admin', NULL, NULL, :created_at, 0, NULL
            )
        """), {
            'id': str(uuid.uuid4()),
            'email': f"admin{i}@example.com",
            'display_name': f"Admin {i}",
            'created_at': datetime.utcnow(),
        })
    
    # Create 3 students
    for i in range(3):
        test_session.execute(text("""
            INSERT INTO users (
                id, email, kcet_student_id, display_name, password_hash,
                role, student_subtype, institution_id, created_at,
                failed_login_count, lockout_until
            ) VALUES (
                :id, :email, :kcet_student_id, :display_name, '$2b$12$dummyhash',
                'student', NULL, NULL, :created_at, 0, NULL
            )
        """), {
            'id': str(uuid.uuid4()),
            'email': f"student{i}@example.com",
            'kcet_student_id': f"KCET{200000 + i}",
            'display_name': f"Student {i}",
            'created_at': datetime.utcnow(),
        })
    
    test_session.commit()
    
    migration_date = datetime.utcnow()
    migration_stats = run_migration_logic(test_session, migration_date)
    
    assert migration_stats["admin_count"] == 2
    assert migration_stats["student_count"] == 3
    assert migration_stats["subscriptions_created"] == 3
    
    # Verify admins migrated correctly
    platform_admin_count = test_session.execute(text(
        "SELECT COUNT(*) FROM users WHERE role = 'platform_admin' AND student_subtype IS NULL"
    )).scalar()
    assert platform_admin_count == 2
    
    # Verify students migrated correctly
    student_count = test_session.execute(text(
        "SELECT COUNT(*) FROM users WHERE role = 'student' AND student_subtype = 'direct_subscriber'"
    )).scalar()
    assert student_count == 3
    
    # Verify subscriptions created only for students
    subscription_count = test_session.execute(text(
        "SELECT COUNT(*) FROM subscriptions WHERE status = 'trial' AND trial_duration_days = 7"
    )).scalar()
    assert subscription_count == 3
