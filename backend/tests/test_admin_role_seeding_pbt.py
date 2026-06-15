"""Property-based test for admin role seeding bug condition.

This module contains a property-based test using Hypothesis to validate
that the admin user is seeded with the correct role='platform_admin'.

Feature: subscription-platform-bugfix, Bug 3: Admin Role Incorrect
Property: Fix Checking - Admin has correct role

Bug Condition Function:
  WHEN the admin account is seeded on platform startup
  THEN the user role SHALL be set to 'platform_admin' 
  (NOT 'admin' or any other value)

Expected Behavior:
  Admin user has role='platform_admin' after seeding
"""

import os
from datetime import datetime
from typing import Optional
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.seed import seed_admin
from smartkcet.db.session import SessionLocal


# =============================================================================
# Test Database Setup
# =============================================================================


@pytest.fixture
def in_memory_db_session():
    """Create an in-memory test database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    
    SessionLocal_test = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )
    session = SessionLocal_test()
    
    yield session
    
    session.close()
    engine.dispose()


# =============================================================================
# Hypothesis Strategies
# =============================================================================


@st.composite
def admin_credentials_strategy(draw):
    """Generate valid admin credentials for seeding."""
    # Valid bcrypt hash format (60 chars: $2b$12$ + 53 chars of hash/salt)
    email = draw(st.emails())
    # Real bcrypt hash from test environment
    password_hash = "$2b$12$f3uoTLLNpevU.MFxEHPavuc3uxV8khHhI4EXSw/IHlRmIMGe4LEiC"
    # Simple display name
    display_name = draw(st.text(
        alphabet=st.characters(blacklist_characters="\x00"),
        min_size=1,
        max_size=50
    )).strip() or "Administrator"
    
    return {
        "email": email,
        "password_hash": password_hash,
        "display_name": display_name
    }


# =============================================================================
# Main Property-Based Test
# =============================================================================


@given(admin_creds=admin_credentials_strategy())
@settings(max_examples=5, deadline=None, suppress_health_check=[])
def test_admin_role_seed_property(admin_creds):
    """
    **Validates: Requirements 1.4, 2.4**
    
    Property: Fix Checking - Admin Role Correct After Seeding
    
    FOR ALL admin seeding operations with fresh database:
      - Admin user exists in database after seed_admin()
      - Admin role = 'platform_admin' (NOT 'admin' or other values)
      - Admin email matches expected value
      - Admin display_name matches expected value
      - No duplicate admin records created (idempotent)
    
    This test MUST FAIL on unfixed code where role is set to 'admin'.
    """
    # Create fresh in-memory database for this example
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    
    SessionLocal_test = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )
    session = SessionLocal_test()
    
    try:
        # Set environment variables for admin seeding
        with _set_admin_env(admin_creds):
            # Call seed_admin()
            result = seed_admin(session=session)
            
            # ASSERTION 1: Admin user was created or is already up-to-date
            assert result in ["created", "unchanged", "updated"], (
                f"Expected seed_admin to return 'created'/'unchanged'/'updated', "
                f"got '{result}'"
            )
            
            # ASSERTION 2: Query database for admin user by email
            admin_user = session.query(User).filter(
                User.email == admin_creds["email"]
            ).one_or_none()
            
            assert admin_user is not None, (
                f"Admin user with email '{admin_creds['email']}' not found in database"
            )
            
            # ASSERTION 3: Admin role = 'platform_admin' (CRITICAL - Bug check)
            assert admin_user.role == "platform_admin", (
                f"BUG DETECTED: Admin user has role='{admin_user.role}' "
                f"instead of 'platform_admin'. This indicates the bug exists."
            )
            
            # ASSERTION 4: Admin email matches
            assert admin_user.email == admin_creds["email"], (
                f"Admin email mismatch: expected '{admin_creds['email']}', "
                f"got '{admin_user.email}'"
            )
            
            # ASSERTION 5: Admin display_name matches
            assert admin_user.display_name == admin_creds["display_name"], (
                f"Admin display_name mismatch: expected '{admin_creds['display_name']}', "
                f"got '{admin_user.display_name}'"
            )
            
            # ASSERTION 6: Admin kcet_student_id should be None
            assert admin_user.kcet_student_id is None, (
                f"Admin should not have kcet_student_id, got '{admin_user.kcet_student_id}'"
            )
            
            # ASSERTION 7: Only one admin exists (idempotent check)
            admin_count = session.query(User).filter(
                User.role == "platform_admin"
            ).count()
            assert admin_count == 1, (
                f"Expected exactly 1 platform_admin user, found {admin_count}. "
                f"Seeding may not be idempotent."
            )
            
            # ASSERTION 8: Call seed_admin again - should be idempotent
            second_result = seed_admin(session=session)
            assert second_result == "unchanged", (
                f"Expected seed_admin to return 'unchanged' on second call, "
                f"got '{second_result}'. Seeding is not idempotent."
            )
            
            # ASSERTION 9: Still only one admin after second call
            admin_count_after = session.query(User).filter(
                User.role == "platform_admin"
            ).count()
            assert admin_count_after == 1, (
                f"After idempotent call, expected 1 platform_admin, "
                f"found {admin_count_after}. Duplicates created!"
            )
            
            # ASSERTION 10: Admin data unchanged after idempotent call
            admin_user_after = session.query(User).filter(
                User.email == admin_creds["email"]
            ).one()
            
            assert admin_user_after.role == "platform_admin"
            assert admin_user_after.email == admin_creds["email"]
            assert admin_user_after.display_name == admin_creds["display_name"]
    finally:
        session.close()
        engine.dispose()


# =============================================================================
# Edge Case: Fresh Database Seeding
# =============================================================================


def test_admin_seed_fresh_database_edge_case(in_memory_db_session):
    """
    Edge case: Admin seeding on completely fresh database (0 users).
    
    This tests the exact scenario described in the bug:
    - Fresh database with no existing users
    - seed_admin() called
    - Admin user is created
    - Role MUST be 'platform_admin', NOT 'admin'
    """
    session = in_memory_db_session
    
    # Verify database is empty
    user_count = session.query(User).count()
    assert user_count == 0, "Database should start empty"
    
    admin_email = "admin@smartkcet.com"
    admin_hash = "$2b$12$f3uoTLLNpevU.MFxEHPavuc3uxV8khHhI4EXSw/IHlRmIMGe4LEiC"
    admin_name = "Test Administrator"
    
    with _set_admin_env({
        "email": admin_email,
        "password_hash": admin_hash,
        "display_name": admin_name
    }):
        # Seed admin
        result = seed_admin(session=session)
        assert result == "created", "First seed should create admin"
        
        # Query fresh-seeded admin
        admin = session.query(User).filter(
            User.email == admin_email
        ).one()
        
        # CRITICAL BUG CHECK
        assert admin.role == "platform_admin", (
            f"FRESH DATABASE BUG: Admin was seeded with role='{admin.role}' "
            f"instead of 'platform_admin'. This is the bug condition!"
        )
        
        # Verify all expected fields
        assert admin.email == admin_email
        assert admin.display_name == admin_name
        assert admin.kcet_student_id is None
        assert admin.password_hash == admin_hash


# =============================================================================
# Edge Case: Admin Role Preservation
# =============================================================================


def test_admin_role_preservation_on_update(in_memory_db_session):
    """
    Edge case: When admin already exists with platform_admin role, seeding
    should recognize it and leave it unchanged (idempotent).
    
    NOTE: In the bugfix, the database CHECK constraint now enforces that
    role must be 'platform_admin', 'institution_admin', or 'student'.
    The old buggy value 'admin' is no longer valid, so we test that
    seeding correctly handles an existing platform_admin user.
    """
    session = in_memory_db_session
    
    admin_email = "admin@smartkcet.com"
    admin_hash = "$2b$12$f3uoTLLNpevU.MFxEHPavuc3uxV8khHhI4EXSw/IHlRmIMGe4LEiC"
    
    # Create an existing admin user with correct role
    existing_admin = User(
        email=admin_email,
        kcet_student_id=None,
        display_name="Existing Admin",
        password_hash="old_hash",
        role="platform_admin"  # Correct role
    )
    session.add(existing_admin)
    session.commit()
    
    # Now seed_admin should recognize it and be idempotent
    with _set_admin_env({
        "email": admin_email,
        "password_hash": admin_hash,
        "display_name": "Updated Admin"
    }):
        result = seed_admin(session=session)
        
        # Should recognize existing admin and be idempotent
        assert result in ["updated", "unchanged"], (
            f"Expected seed_admin to update or leave existing admin unchanged, got '{result}'"
        )
        
        # Verify role remains platform_admin
        admin = session.query(User).filter(
            User.email == admin_email
        ).one()
        
        assert admin.role == "platform_admin", (
            f"Admin role should remain 'platform_admin', but it's '{admin.role}'"
        )


# =============================================================================
# Preservation Test: Non-Admin Users Unchanged
# =============================================================================


def test_admin_seeding_does_not_affect_students(in_memory_db_session):
    """
    Preservation Property: Admin seeding should not modify existing student users.
    
    When student users exist in the database, calling seed_admin() should:
    - Leave their role as 'student'
    - Not modify their data
    - Create or update only the admin user
    """
    session = in_memory_db_session
    
    # Create existing student users
    student1 = User(
        email="student1@test.com",
        kcet_student_id="KCET001",
        display_name="Student One",
        password_hash="hash1",
        role="student",
        student_subtype="direct_subscriber"
    )
    student2 = User(
        email="student2@test.com",
        kcet_student_id="KCET002",
        display_name="Student Two",
        password_hash="hash2",
        role="student",
        student_subtype="institution_linked"
    )
    session.add_all([student1, student2])
    session.commit()
    
    # Record student data before seeding
    student1_before = session.query(User).filter(
        User.email == "student1@test.com"
    ).one()
    student1_role_before = student1_before.role
    student1_subtype_before = student1_before.student_subtype
    
    # Seed admin
    with _set_admin_env({
        "email": "admin@smartkcet.com",
        "password_hash": "$2b$12$f3uoTLLNpevU.MFxEHPavuc3uxV8khHhI4EXSw/IHlRmIMGe4LEiC",
        "display_name": "Admin"
    }):
        seed_admin(session=session)
    
    # Verify students unchanged
    student1_after = session.query(User).filter(
        User.email == "student1@test.com"
    ).one()
    
    assert student1_after.role == student1_role_before, (
        f"Student1 role changed from '{student1_role_before}' to '{student1_after.role}'"
    )
    assert student1_after.student_subtype == student1_subtype_before, (
        f"Student1 subtype changed from '{student1_subtype_before}' "
        f"to '{student1_after.student_subtype}'"
    )
    
    # Verify admin was created
    admin = session.query(User).filter(
        User.email == "admin@smartkcet.com"
    ).one()
    assert admin.role == "platform_admin"


# =============================================================================
# Helper Functions
# =============================================================================


class _set_admin_env:
    """Context manager to temporarily set admin environment variables."""
    
    def __init__(self, creds: dict):
        self.creds = creds
        self.old_env = {}
    
    def __enter__(self):
        self.old_env["ADMIN_EMAIL"] = os.environ.get("ADMIN_EMAIL")
        self.old_env["ADMIN_PASSWORD_HASH"] = os.environ.get("ADMIN_PASSWORD_HASH")
        self.old_env["ADMIN_DISPLAY_NAME"] = os.environ.get("ADMIN_DISPLAY_NAME")
        
        os.environ["ADMIN_EMAIL"] = self.creds["email"]
        os.environ["ADMIN_PASSWORD_HASH"] = self.creds["password_hash"]
        os.environ["ADMIN_DISPLAY_NAME"] = self.creds["display_name"]
        
        return self
    
    def __exit__(self, *args):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
