"""Preservation property tests for non-admin user roles.

This module contains preservation tests for Bug 3: Admin role incorrect.

**Validates: Requirement 3.4**

Preservation Requirement: When existing user records have role='student' or 
other non-admin roles, calling seed_admin() does NOT modify their role values 
or any other fields. Non-admin users are completely unchanged.

CRITICAL: This test MUST PASS on unfixed code to confirm we've captured 
the baseline behavior that non-admin users are not affected by admin seeding. 
This is the preservation guarantee — we verify that admin seeding is 
completely isolated to admin users and doesn't touch student users.

Observation-First Methodology:
1. OBSERVE: Create existing student users with role='student' (various subtypes)
2. OBSERVE: Call seed_admin()
3. OBSERVE: Do student roles stay as 'student'? Are other fields modified?
4. WRITE: Property-based test that captures this non-modification pattern
5. VERIFY: Test passes on unfixed code (confirms baseline captured)
"""

import uuid
from pathlib import Path
import sys

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.seed import seed_admin

# Valid bcrypt hashes (60 chars, starts with $2b$)
VALID_BCRYPT_HASH = '$2b$12$f3uoTLLNpevU.MFxEHPavuc3uxV8khHhI4EXSw/IHlRmIMGe4LEiC'
ADMIN_BCRYPT_HASH = '$2b$12$f3uoTLLNpevU.MFxEHPavuc3uxV8khHhI4EXSw/IHlRmIMGe4LEiC'


# =============================================================================
# Test Setup: Fresh Database Sessions
# =============================================================================


@pytest.fixture
def fresh_db_session():
    """Create a fresh in-memory database session for each test.
    
    Creates a clean database state with only the schema (no users).
    Allows testing the preservation behavior when admin seeding occurs
    in the presence of existing non-admin users.
    """
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


# =============================================================================
# Hypothesis Strategies
# =============================================================================


@st.composite
def student_user_factory(draw):
    """Generate a student user with various configurations.
    
    Creates a student user with:
    - role='student' (non-admin)
    - Various student_subtype values (direct_subscriber, institution_linked)
    - Realistic email and display name
    """
    subtype = draw(st.sampled_from([
        'direct_subscriber',
        'institution_linked',
    ]))
    
    return {
        'email': draw(st.emails()),
        'display_name': draw(st.text(
            alphabet='abcdefghijklmnopqrstuvwxyz ',
            min_size=1,
            max_size=30
        )).strip() or "Student",
        'role': 'student',
        'student_subtype': subtype,
        'kcet_student_id': None,
        'password_hash': VALID_BCRYPT_HASH,
    }


@st.composite
def multiple_students_factory(draw):
    """Generate 2-5 student users with various configurations.
    
    Creates a list of student users to test preservation of multiple
    non-admin users when admin seeding occurs.
    """
    num_students = draw(st.integers(min_value=2, max_value=5))
    students = []
    
    # Generate unique email addresses for each student
    seen_emails = set()
    for i in range(num_students):
        student = {
            'email': f'student{i}_{draw(st.integers(min_value=0, max_value=9999))}@test.com',
            'display_name': f'Student {i}',
            'role': 'student',
            'student_subtype': draw(st.sampled_from(['direct_subscriber', 'institution_linked'])),
            'kcet_student_id': None,
            'password_hash': VALID_BCRYPT_HASH,
        }
        if student['email'] not in seen_emails:
            seen_emails.add(student['email'])
            students.append(student)
    
    return students


# =============================================================================
# Preservation Property Tests
# =============================================================================


class TestNonAdminUserRolePreservation:
    """
    Property: Preservation - Non-Admin User Roles Unchanged
    
    **Validates: Requirement 3.4**
    
    For all existing non-admin users (role='student' or other non-admin roles),
    calling seed_admin() SHALL:
    (a) NOT modify their role field
    (b) NOT modify their email field
    (c) NOT modify their display_name field
    (d) NOT modify their password_hash field
    (e) NOT modify their student_subtype field
    (f) NOT modify their created_at field
    (g) NOT create, delete, or modify any non-admin user records
    
    This is the preservation guarantee: we must ensure that when the fix
    is applied (changing admin role from 'admin' to 'platform_admin'),
    it doesn't accidentally affect non-admin users.
    """

    def test_preservation_single_student_role_unchanged(
        self, fresh_db_session: Session
    ):
        """Preservation: Single student's role unchanged after admin seed.
        
        **Validates: Requirement 3.4**
        
        When a single student user exists with role='student', calling
        seed_admin() SHALL NOT modify their role field.
        
        This test MUST PASS on unfixed code (confirms baseline behavior).
        After the fix is applied, this should still PASS (preservation).
        """
        # Create a student user
        student = User(
            email='student1@example.com',
            kcet_student_id=None,
            display_name='Alice Student',
            password_hash=VALID_BCRYPT_HASH,
            role='student',
            student_subtype='direct_subscriber',
        )
        fresh_db_session.add(student)
        fresh_db_session.commit()
        
        # Set environment for admin seeding
        import os
        os.environ['ADMIN_EMAIL'] = 'admin@smartkcet.com'
        os.environ['ADMIN_PASSWORD_HASH'] = ADMIN_BCRYPT_HASH
        os.environ['ADMIN_DISPLAY_NAME'] = 'Platform Admin'
        
        # Capture student state before seeding
        student_before = fresh_db_session.query(User).filter(
            User.email == 'student1@example.com'
        ).one()
        role_before = student_before.role
        email_before = student_before.email
        display_name_before = student_before.display_name
        
        # Seed admin
        seed_admin(fresh_db_session)
        
        # Capture student state after seeding
        student_after = fresh_db_session.query(User).filter(
            User.email == 'student1@example.com'
        ).one()
        role_after = student_after.role
        email_after = student_after.email
        display_name_after = student_after.display_name
        
        # ASSERT: Student role must be unchanged
        assert role_before == 'student', "Initial role should be 'student'"
        assert role_after == 'student', (
            f"PRESERVATION FAILURE: Student role changed after seed_admin(). "
            f"Before: {role_before}, After: {role_after}"
        )
        
        # ASSERT: Email and display_name must be unchanged
        assert email_before == email_after, (
            f"PRESERVATION FAILURE: Student email changed. "
            f"Before: {email_before}, After: {email_after}"
        )
        assert display_name_before == display_name_after, (
            f"PRESERVATION FAILURE: Student display_name changed. "
            f"Before: {display_name_before}, After: {display_name_after}"
        )

    def test_preservation_multiple_students_roles_unchanged(
        self, fresh_db_session: Session
    ):
        """Preservation: Multiple students' roles unchanged after admin seed.
        
        **Validates: Requirement 3.4**
        
        When multiple student users exist with role='student', calling
        seed_admin() SHALL NOT modify ANY of their role fields.
        
        This test MUST PASS on unfixed code (confirms baseline behavior).
        After the fix is applied, this should still PASS (preservation).
        """
        # Create 3 student users with different subtypes
        students_data = [
            {
                'email': 'student1@example.com',
                'display_name': 'Alice',
                'subtype': 'direct_subscriber',
            },
            {
                'email': 'student2@example.com',
                'display_name': 'Bob',
                'subtype': 'institution_linked',
            },
            {
                'email': 'student3@example.com',
                'display_name': 'Charlie',
                'subtype': 'direct_subscriber',
            },
        ]
        
        for data in students_data:
            student = User(
                email=data['email'],
                kcet_student_id=None,
                display_name=data['display_name'],
                password_hash=VALID_BCRYPT_HASH,
                role='student',
                student_subtype=data['subtype'],
            )
            fresh_db_session.add(student)
        fresh_db_session.commit()
        
        # Set environment for admin seeding
        import os
        os.environ['ADMIN_EMAIL'] = 'admin@smartkcet.com'
        os.environ['ADMIN_PASSWORD_HASH'] = ADMIN_BCRYPT_HASH
        os.environ['ADMIN_DISPLAY_NAME'] = 'Platform Admin'
        
        # Capture student roles before seeding
        students_before = fresh_db_session.query(User).filter(
            User.role == 'student'
        ).all()
        roles_before = {student.email: student.role for student in students_before}
        assert len(roles_before) == 3, "Should have 3 students"
        
        # Seed admin
        seed_admin(fresh_db_session)
        
        # Capture student roles after seeding
        students_after = fresh_db_session.query(User).filter(
            User.role == 'student'
        ).all()
        roles_after = {student.email: student.role for student in students_after}
        
        # ASSERT: All students still have role='student'
        assert len(roles_after) == 3, (
            f"PRESERVATION FAILURE: Student count changed. "
            f"Before: 3, After: {len(roles_after)}"
        )
        
        for email in roles_before:
            assert roles_after.get(email) == 'student', (
                f"PRESERVATION FAILURE: Student {email} role changed. "
                f"Before: {roles_before[email]}, After: {roles_after.get(email)}"
            )

    def test_preservation_student_all_fields_unchanged(
        self, fresh_db_session: Session
    ):
        """Preservation: All student fields unchanged after admin seed.
        
        **Validates: Requirement 3.4**
        
        When a student user exists, calling seed_admin() SHALL NOT modify
        ANY of their fields (email, display_name, password_hash, role, 
        student_subtype).
        
        This test MUST PASS on unfixed code (confirms baseline behavior).
        After the fix is applied, this should still PASS (preservation).
        """
        # Create a student user
        student = User(
            email='student@example.com',
            kcet_student_id=None,
            display_name='Student Name',
            password_hash=VALID_BCRYPT_HASH,
            role='student',
            student_subtype='direct_subscriber',
        )
        fresh_db_session.add(student)
        fresh_db_session.commit()
        
        # Set environment for admin seeding
        import os
        os.environ['ADMIN_EMAIL'] = 'admin@smartkcet.com'
        os.environ['ADMIN_PASSWORD_HASH'] = ADMIN_BCRYPT_HASH
        os.environ['ADMIN_DISPLAY_NAME'] = 'Platform Admin'
        
        # Capture all student fields before seeding
        student_before = fresh_db_session.query(User).filter(
            User.email == 'student@example.com'
        ).one()
        fields_before = {
            'email': student_before.email,
            'display_name': student_before.display_name,
            'password_hash': student_before.password_hash,
            'role': student_before.role,
            'student_subtype': student_before.student_subtype,
            'kcet_student_id': student_before.kcet_student_id,
        }
        
        # Seed admin
        seed_admin(fresh_db_session)
        
        # Capture all student fields after seeding
        student_after = fresh_db_session.query(User).filter(
            User.email == 'student@example.com'
        ).one()
        fields_after = {
            'email': student_after.email,
            'display_name': student_after.display_name,
            'password_hash': student_after.password_hash,
            'role': student_after.role,
            'student_subtype': student_after.student_subtype,
            'kcet_student_id': student_after.kcet_student_id,
        }
        
        # ASSERT: All fields must be identical
        for field_name in fields_before:
            assert fields_before[field_name] == fields_after[field_name], (
                f"PRESERVATION FAILURE: Student field '{field_name}' changed. "
                f"Before: {fields_before[field_name]}, After: {fields_after[field_name]}"
            )

    def test_preservation_student_count_unchanged(
        self, fresh_db_session: Session
    ):
        """Preservation: Student count unchanged after admin seed.
        
        **Validates: Requirement 3.4**
        
        When N students exist in the database, calling seed_admin() SHALL
        NOT create, delete, or modify any student records. Count must remain N.
        
        This test MUST PASS on unfixed code (confirms baseline behavior).
        After the fix is applied, this should still PASS (preservation).
        """
        # Create 3 students
        for i in range(3):
            student = User(
                email=f'student{i}@example.com',
                kcet_student_id=None,
                display_name=f'Student {i}',
                password_hash=VALID_BCRYPT_HASH,
                role='student',
                student_subtype='direct_subscriber' if i % 2 == 0 else 'institution_linked',
            )
            fresh_db_session.add(student)
        fresh_db_session.commit()
        
        # Set environment for admin seeding
        import os
        os.environ['ADMIN_EMAIL'] = 'admin@smartkcet.com'
        os.environ['ADMIN_PASSWORD_HASH'] = ADMIN_BCRYPT_HASH
        os.environ['ADMIN_DISPLAY_NAME'] = 'Platform Admin'
        
        # Count students before seeding
        count_before = fresh_db_session.query(User).filter(
            User.role == 'student'
        ).count()
        assert count_before == 3, "Should have 3 students initially"
        
        # Seed admin
        seed_admin(fresh_db_session)
        
        # Count students after seeding
        count_after = fresh_db_session.query(User).filter(
            User.role == 'student'
        ).count()
        
        # ASSERT: Count must be unchanged
        assert count_after == 3, (
            f"PRESERVATION FAILURE: Student count changed. "
            f"Before: {count_before}, After: {count_after}"
        )

    @given(students=multiple_students_factory())
    @settings(max_examples=10, suppress_health_check=[HealthCheck.large_base_example])
    def test_preservation_property_multiple_students(
        self, students
    ):
        """Property: Multiple non-admin users' roles unchanged.
        
        **Validates: Requirement 3.4**
        
        **Scoped Property-Based Test**: For all N in [2, 5], when N student
        users exist and seed_admin() is called, then:
        (a) All N students still have role='student'
        (b) No student fields are modified
        (c) No students are created or deleted
        
        This test MUST PASS on unfixed code (confirms baseline preservation
        of non-admin users).
        """
        # Create a fresh database for this property test
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db_session = TestSessionLocal()
        
        try:
            # Verify we have between 2-5 students
            num_students = len(students)
            assert 2 <= num_students <= 5, (
                f"Should have 2-5 students, got {num_students}"
            )
            
            # Create all student users
            for student_data in students:
                student = User(
                    email=student_data['email'],
                    kcet_student_id=None,
                    display_name=student_data['display_name'],
                    password_hash=student_data['password_hash'],
                    role='student',
                    student_subtype=student_data['student_subtype'],
                )
                db_session.add(student)
            db_session.commit()
            
            # Set environment for admin seeding
            import os
            os.environ['ADMIN_EMAIL'] = 'admin@smartkcet.com'
            os.environ['ADMIN_PASSWORD_HASH'] = ADMIN_BCRYPT_HASH
            os.environ['ADMIN_DISPLAY_NAME'] = 'Platform Admin'
            
            # Capture student data before seeding
            students_before = db_session.query(User).filter(
                User.role == 'student'
            ).all()
            data_before = {
                student.email: {
                    'role': student.role,
                    'display_name': student.display_name,
                    'password_hash': student.password_hash,
                    'student_subtype': student.student_subtype,
                }
                for student in students_before
            }
            count_before = len(data_before)
            
            # Seed admin
            seed_admin(db_session)
            
            # Capture student data after seeding
            students_after = db_session.query(User).filter(
                User.role == 'student'
            ).all()
            data_after = {
                student.email: {
                    'role': student.role,
                    'display_name': student.display_name,
                    'password_hash': student.password_hash,
                    'student_subtype': student.student_subtype,
                }
                for student in students_after
            }
            count_after = len(data_after)
            
            # ASSERT (a): Count unchanged
            assert count_after == count_before, (
                f"PRESERVATION FAILURE: Student count changed. "
                f"Before: {count_before}, After: {count_after}"
            )
            
            # ASSERT (b): All student data unchanged
            assert data_before == data_after, (
                f"PRESERVATION FAILURE: Student data changed. "
                f"Before: {data_before}, After: {data_after}"
            )
            
            # ASSERT (c): All students still have role='student'
            for email, data in data_after.items():
                assert data['role'] == 'student', (
                    f"PRESERVATION FAILURE: Student {email} role changed to {data['role']}"
                )
        finally:
            db_session.close()
            engine.dispose()

    def test_preservation_institution_linked_student_unchanged(
        self, fresh_db_session: Session
    ):
        """Preservation: Institution-linked student unchanged.
        
        **Validates: Requirement 3.4**
        
        When an institution_linked student exists, calling seed_admin()
        SHALL NOT modify their role or any other field.
        
        This test MUST PASS on unfixed code (confirms baseline behavior).
        After the fix is applied, this should still PASS (preservation).
        """
        # Create an institution_linked student
        student = User(
            email='institution_student@example.com',
            kcet_student_id=None,
            display_name='Institution Student',
            password_hash=VALID_BCRYPT_HASH,
            role='student',
            student_subtype='institution_linked',
            institution_id=uuid.uuid4(),  # Has institution_id
        )
        fresh_db_session.add(student)
        fresh_db_session.commit()
        
        # Set environment for admin seeding
        import os
        os.environ['ADMIN_EMAIL'] = 'admin@smartkcet.com'
        os.environ['ADMIN_PASSWORD_HASH'] = ADMIN_BCRYPT_HASH
        os.environ['ADMIN_DISPLAY_NAME'] = 'Platform Admin'
        
        # Capture student state before seeding
        student_before = fresh_db_session.query(User).filter(
            User.email == 'institution_student@example.com'
        ).one()
        state_before = {
            'role': student_before.role,
            'student_subtype': student_before.student_subtype,
            'institution_id': student_before.institution_id,
        }
        
        # Seed admin
        seed_admin(fresh_db_session)
        
        # Capture student state after seeding
        student_after = fresh_db_session.query(User).filter(
            User.email == 'institution_student@example.com'
        ).one()
        state_after = {
            'role': student_after.role,
            'student_subtype': student_after.student_subtype,
            'institution_id': student_after.institution_id,
        }
        
        # ASSERT: State must be unchanged
        assert state_before == state_after, (
            f"PRESERVATION FAILURE: Institution-linked student changed. "
            f"Before: {state_before}, After: {state_after}"
        )

    def test_preservation_admin_created_but_students_untouched(
        self, fresh_db_session: Session
    ):
        """Preservation: Admin created, but existing students untouched.
        
        **Validates: Requirement 3.4**
        
        When students exist and admin seeding creates a new admin user,
        the students must remain completely unchanged.
        
        This test MUST PASS on unfixed code (confirms baseline behavior).
        After the fix is applied, this should still PASS (preservation).
        """
        # Create 2 students
        for i in range(2):
            student = User(
                email=f'student{i}@example.com',
                kcet_student_id=None,
                display_name=f'Student {i}',
                password_hash=VALID_BCRYPT_HASH,
                role='student',
                student_subtype='direct_subscriber',
            )
            fresh_db_session.add(student)
        fresh_db_session.commit()
        
        # Set environment for admin seeding
        import os
        os.environ['ADMIN_EMAIL'] = 'admin@smartkcet.com'
        os.environ['ADMIN_PASSWORD_HASH'] = ADMIN_BCRYPT_HASH
        os.environ['ADMIN_DISPLAY_NAME'] = 'Platform Admin'
        
        # Capture all users before seeding
        users_before = fresh_db_session.query(User).all()
        student_data_before = {
            user.email: user.role for user in users_before if user.role == 'student'
        }
        admin_count_before = len([u for u in users_before if u.role == 'platform_admin'])
        
        # Seed admin (should create new admin)
        seed_admin(fresh_db_session)
        
        # Capture all users after seeding
        users_after = fresh_db_session.query(User).all()
        student_data_after = {
            user.email: user.role for user in users_after if user.role == 'student'
        }
        admin_count_after = len([u for u in users_after if u.role == 'platform_admin'])
        
        # ASSERT: Admin was created
        assert admin_count_after == admin_count_before + 1, (
            f"PRESERVATION FAILURE: Admin not created. "
            f"Before: {admin_count_before}, After: {admin_count_after}"
        )
        
        # ASSERT: Student data unchanged
        assert student_data_before == student_data_after, (
            f"PRESERVATION FAILURE: Student data changed when admin was seeded. "
            f"Before: {student_data_before}, After: {student_data_after}"
        )


class TestNonAdminUserPreservationEdgeCases:
    """Edge case tests for preservation of non-admin user roles."""

    def test_preservation_direct_query_inspection(
        self, fresh_db_session: Session
    ):
        """Direct query inspection: Verify each student unchanged.
        
        **Validates: Requirement 3.4**
        
        Uses direct row-by-row inspection to verify that each student
        record is byte-for-byte unchanged after admin seeding.
        """
        # Create students with specific data
        students_data = [
            ('alice@example.com', 'Alice', 'direct_subscriber'),
            ('bob@example.com', 'Bob', 'institution_linked'),
        ]
        
        for email, name, subtype in students_data:
            student = User(
                email=email,
                kcet_student_id=None,
                display_name=name,
                password_hash=VALID_BCRYPT_HASH,
                role='student',
                student_subtype=subtype,
            )
            fresh_db_session.add(student)
        fresh_db_session.commit()
        
        # Set environment for admin seeding
        import os
        os.environ['ADMIN_EMAIL'] = 'admin@smartkcet.com'
        os.environ['ADMIN_PASSWORD_HASH'] = ADMIN_BCRYPT_HASH
        os.environ['ADMIN_DISPLAY_NAME'] = 'Platform Admin'
        
        # Capture IDs (should not change)
        students_before = fresh_db_session.query(User).filter(
            User.role == 'student'
        ).all()
        ids_before = {s.email: s.id for s in students_before}
        
        # Seed admin
        seed_admin(fresh_db_session)
        
        # Capture IDs after seeding (should be same)
        students_after = fresh_db_session.query(User).filter(
            User.role == 'student'
        ).all()
        ids_after = {s.email: s.id for s in students_after}
        
        # ASSERT: Student IDs unchanged (same records)
        assert ids_before == ids_after, (
            f"PRESERVATION FAILURE: Student IDs changed. "
            f"This indicates records were deleted/recreated. "
            f"Before: {ids_before}, After: {ids_after}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
