"""Unit tests for institution invitation flow (Task 6.3).

Tests the InstitutionService invitation flow methods:
- generate_invitation(): Generate secure invitation codes
- accept_invitation(): Link students to institutions
- remove_student(): Unlink students and free seats

**Requirements:** 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.auth.passwords import hash_password
from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.subscription_models import (
    Institution,
    Invitation,
    Subscription,
    SubscriptionPlan,
)
from smartkcet.institution.service import (
    DatabaseUnavailableError,
    InstitutionService,
    InstitutionServiceError,
)


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
def institution_with_subscription(db_session: Session):
    """Create a test institution with an active subscription."""
    # Create institution
    institution = Institution(
        name="Test Institution",
        contact_phone="1234567890",
        subscription_status="active",
        registered_at=datetime.utcnow(),
    )
    db_session.add(institution)
    db_session.flush()
    
    # Create subscription plan with 10 seats
    plan = SubscriptionPlan(
        name="Institution Plan",
        plan_type="institution",
        billing_period="monthly",
        price=1000.00,
        max_test_attempts_per_period=None,  # Unlimited
        max_student_seats=10,
        feature_flags={},
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(plan)
    db_session.flush()
    
    # Create active subscription
    subscription = Subscription(
        user_id=None,
        institution_id=institution.id,
        plan_id=plan.id,
        status="active",
        start_date=datetime.utcnow(),
        current_period_start=datetime.utcnow(),
        next_renewal_date=datetime.utcnow() + timedelta(days=30),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(subscription)
    db_session.commit()
    
    return institution


@pytest.fixture
def student_user(db_session: Session):
    """Create a test student user."""
    student = User(
        email="student@test.com",
        kcet_student_id="KCET123",
        display_name="Test Student",
        password_hash=hash_password("password123"),
        role="student",
        student_subtype=None,
        institution_id=None,
        created_at=datetime.utcnow(),
        failed_login_count=0,
        lockout_until=None,
    )
    db_session.add(student)
    db_session.commit()
    return student


class TestGenerateInvitation:
    """Test suite for generate_invitation()."""

    def test_successful_invitation_generation(
        self, db_session: Session, institution_with_subscription: Institution
    ):
        """Test successful invitation code generation."""
        service = InstitutionService(db_session)
        
        result = service.generate_invitation(institution_with_subscription.id)
        
        # Verify response
        assert result.id is not None
        assert result.code is not None
        assert len(result.code) >= 32  # Minimum 32 characters
        assert result.institution_id == institution_with_subscription.id
        assert result.status == "pending"
        assert result.created_at is not None
        assert result.expires_at is not None
        
        # Verify expiry is 7 days from now
        expected_expiry = result.created_at + timedelta(days=7)
        time_diff = abs((result.expires_at - expected_expiry).total_seconds())
        assert time_diff < 2  # Within 2 seconds
        
        # Verify invitation record created in DB
        invitation = db_session.query(Invitation).filter_by(
            id=result.id
        ).first()
        assert invitation is not None
        assert invitation.code == result.code
        assert invitation.status == "pending"
        assert invitation.consumed_by is None
        assert invitation.consumed_at is None

    def test_invitation_code_uniqueness(
        self, db_session: Session, institution_with_subscription: Institution
    ):
        """Test that generated invitation codes are unique."""
        service = InstitutionService(db_session)
        
        # Generate multiple invitations
        codes = set()
        for _ in range(10):
            result = service.generate_invitation(institution_with_subscription.id)
            codes.add(result.code)
        
        # All codes should be unique
        assert len(codes) == 10

    def test_invitation_code_security(
        self, db_session: Session, institution_with_subscription: Institution
    ):
        """Test that invitation codes are cryptographically secure."""
        service = InstitutionService(db_session)
        
        result = service.generate_invitation(institution_with_subscription.id)
        
        # Code should be URL-safe (alphanumeric + - and _)
        assert all(c.isalnum() or c in ['-', '_'] for c in result.code)
        
        # Code should be long enough to be secure (32+ chars)
        assert len(result.code) >= 32

    def test_max_pending_invitations_limit(
        self, db_session: Session, institution_with_subscription: Institution
    ):
        """Test that max 50 pending invitations are enforced."""
        service = InstitutionService(db_session)
        
        # Generate 50 pending invitations
        for _ in range(50):
            service.generate_invitation(institution_with_subscription.id)
        
        # 51st invitation should fail
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.generate_invitation(institution_with_subscription.id)
        
        assert "50" in str(exc_info.value)
        assert "pending" in str(exc_info.value).lower()

    def test_consumed_invitations_not_counted(
        self, db_session: Session, institution_with_subscription: Institution
    ):
        """Test that consumed invitations don't count toward the 50 limit."""
        service = InstitutionService(db_session)
        
        # Generate 50 invitations and mark them as consumed
        for _ in range(50):
            result = service.generate_invitation(institution_with_subscription.id)
            invitation = db_session.query(Invitation).filter_by(
                id=result.id
            ).first()
            invitation.status = "consumed"
            db_session.commit()
        
        # Should be able to generate more since consumed ones don't count
        result = service.generate_invitation(institution_with_subscription.id)
        assert result.id is not None

    def test_expired_invitations_not_counted(
        self, db_session: Session, institution_with_subscription: Institution
    ):
        """Test that expired invitations don't count toward the 50 limit."""
        service = InstitutionService(db_session)
        
        # Generate 50 invitations and mark them as expired
        for _ in range(50):
            result = service.generate_invitation(institution_with_subscription.id)
            invitation = db_session.query(Invitation).filter_by(
                id=result.id
            ).first()
            invitation.status = "expired"
            db_session.commit()
        
        # Should be able to generate more since expired ones don't count
        result = service.generate_invitation(institution_with_subscription.id)
        assert result.id is not None


class TestAcceptInvitation:
    """Test suite for accept_invitation()."""

    def test_successful_invitation_acceptance(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test successful invitation acceptance and student linking."""
        service = InstitutionService(db_session)
        
        # Generate invitation
        invitation = service.generate_invitation(institution_with_subscription.id)
        
        # Accept invitation
        service.accept_invitation(invitation.code, student_user.id)
        
        # Verify student is linked
        db_session.refresh(student_user)
        assert student_user.institution_id == institution_with_subscription.id
        assert student_user.student_subtype == "institution_linked"
        
        # Verify invitation is consumed
        db_invitation = db_session.query(Invitation).filter_by(
            id=invitation.id
        ).first()
        assert db_invitation.status == "consumed"
        assert db_invitation.consumed_by == student_user.id
        assert db_invitation.consumed_at is not None

    def test_invalid_invitation_code(
        self, db_session: Session, student_user: User
    ):
        """Test rejection of invalid invitation code."""
        service = InstitutionService(db_session)
        
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.accept_invitation("invalid_code_12345678901234567890", student_user.id)
        
        assert "invalid" in str(exc_info.value).lower()

    def test_expired_invitation_rejection(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test rejection of expired invitation."""
        service = InstitutionService(db_session)
        
        # Create expired invitation
        invitation = Invitation(
            institution_id=institution_with_subscription.id,
            code="expired_code_12345678901234567890",
            status="pending",
            created_at=datetime.utcnow() - timedelta(days=8),
            expires_at=datetime.utcnow() - timedelta(days=1),
            consumed_by=None,
            consumed_at=None,
        )
        db_session.add(invitation)
        db_session.commit()
        
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.accept_invitation(invitation.code, student_user.id)
        
        assert "expired" in str(exc_info.value).lower()
        
        # Verify student not linked
        db_session.refresh(student_user)
        assert student_user.institution_id is None

    def test_consumed_invitation_rejection(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test rejection of already consumed invitation."""
        service = InstitutionService(db_session)
        
        # Create consumed invitation
        other_student_id = uuid.uuid4()
        invitation = Invitation(
            institution_id=institution_with_subscription.id,
            code="consumed_code_12345678901234567890",
            status="consumed",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=7),
            consumed_by=other_student_id,
            consumed_at=datetime.utcnow(),
        )
        db_session.add(invitation)
        db_session.commit()
        
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.accept_invitation(invitation.code, student_user.id)
        
        assert "consumed" in str(exc_info.value).lower()

    def test_seat_quota_full_rejection(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
    ):
        """Test rejection when institution seat quota is full."""
        service = InstitutionService(db_session)
        
        # Fill all 10 seats
        for i in range(10):
            student = User(
                email=f"student{i}@test.com",
                kcet_student_id=f"KCET{i}",
                display_name=f"Student {i}",
                password_hash=hash_password("password123"),
                role="student",
                student_subtype="institution_linked",
                institution_id=institution_with_subscription.id,
                created_at=datetime.utcnow(),
                failed_login_count=0,
            )
            db_session.add(student)
        db_session.commit()
        
        # Create new student
        new_student = User(
            email="newstudent@test.com",
            kcet_student_id="KCETNEW",
            display_name="New Student",
            password_hash=hash_password("password123"),
            role="student",
            student_subtype=None,
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(new_student)
        db_session.commit()
        
        # Generate invitation
        invitation = service.generate_invitation(institution_with_subscription.id)
        
        # Attempt to accept should fail
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.accept_invitation(invitation.code, new_student.id)
        
        assert "quota full" in str(exc_info.value).lower()
        assert "10/10" in str(exc_info.value)
        
        # Verify student not linked
        db_session.refresh(new_student)
        assert new_student.institution_id is None
        
        # Verify invitation remains valid (REQ-9.4)
        db_invitation = db_session.query(Invitation).filter_by(
            id=invitation.id
        ).first()
        assert db_invitation.status == "pending"

    def test_already_linked_to_different_institution(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test rejection when student already linked to different institution."""
        service = InstitutionService(db_session)
        
        # Create another institution
        other_institution = Institution(
            name="Other Institution",
            contact_phone="9876543210",
            subscription_status="active",
            registered_at=datetime.utcnow(),
        )
        db_session.add(other_institution)
        db_session.commit()
        
        # Link student to other institution
        student_user.institution_id = other_institution.id
        student_user.student_subtype = "institution_linked"
        db_session.commit()
        
        # Generate invitation for first institution
        invitation = service.generate_invitation(institution_with_subscription.id)
        
        # Attempt to accept should fail
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.accept_invitation(invitation.code, student_user.id)
        
        assert "already linked" in str(exc_info.value).lower()
        
        # Verify student still linked to original institution
        db_session.refresh(student_user)
        assert student_user.institution_id == other_institution.id

    def test_idempotent_acceptance(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test that accepting same invitation twice is idempotent."""
        service = InstitutionService(db_session)
        
        # Generate invitation
        invitation = service.generate_invitation(institution_with_subscription.id)
        
        # Accept invitation first time
        service.accept_invitation(invitation.code, student_user.id)
        
        # Accept invitation second time - should succeed without error
        service.accept_invitation(invitation.code, student_user.id)
        
        # Verify student still linked
        db_session.refresh(student_user)
        assert student_user.institution_id == institution_with_subscription.id

    def test_student_subtype_transition_none_to_institution_linked(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test subtype transition from None to institution_linked."""
        service = InstitutionService(db_session)
        
        # Ensure student has no subtype
        student_user.student_subtype = None
        db_session.commit()
        
        # Generate and accept invitation
        invitation = service.generate_invitation(institution_with_subscription.id)
        service.accept_invitation(invitation.code, student_user.id)
        
        # Verify subtype updated
        db_session.refresh(student_user)
        assert student_user.student_subtype == "institution_linked"

    def test_student_subtype_transition_direct_to_dual(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test subtype transition from direct_subscriber to dual."""
        service = InstitutionService(db_session)
        
        # Set student as direct subscriber
        student_user.student_subtype = "direct_subscriber"
        db_session.commit()
        
        # Generate and accept invitation
        invitation = service.generate_invitation(institution_with_subscription.id)
        service.accept_invitation(invitation.code, student_user.id)
        
        # Verify subtype updated to dual
        db_session.refresh(student_user)
        assert student_user.student_subtype == "dual"

    def test_no_active_subscription_rejection(
        self,
        db_session: Session,
        student_user: User,
    ):
        """Test rejection when institution has no active subscription."""
        service = InstitutionService(db_session)
        
        # Create institution without subscription
        institution = Institution(
            name="No Subscription Institution",
            contact_phone="1234567890",
            subscription_status="inactive",
            registered_at=datetime.utcnow(),
        )
        db_session.add(institution)
        db_session.commit()
        
        # Create invitation
        invitation = Invitation(
            institution_id=institution.id,
            code="no_sub_code_12345678901234567890",
            status="pending",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=7),
            consumed_by=None,
            consumed_at=None,
        )
        db_session.add(invitation)
        db_session.commit()
        
        # Attempt to accept should fail
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.accept_invitation(invitation.code, student_user.id)
        
        assert "active subscription" in str(exc_info.value).lower()


class TestRemoveStudent:
    """Test suite for remove_student()."""

    def test_successful_student_removal(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test successful student removal from institution."""
        service = InstitutionService(db_session)
        
        # Link student to institution first
        student_user.institution_id = institution_with_subscription.id
        student_user.student_subtype = "institution_linked"
        db_session.commit()
        
        # Remove student
        service.remove_student(institution_with_subscription.id, student_user.id)
        
        # Verify student unlinked
        db_session.refresh(student_user)
        assert student_user.institution_id is None
        assert student_user.student_subtype is None

    def test_student_not_found(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
    ):
        """Test error when student not found."""
        service = InstitutionService(db_session)
        
        fake_student_id = uuid.uuid4()
        
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.remove_student(institution_with_subscription.id, fake_student_id)
        
        assert "not found" in str(exc_info.value).lower()

    def test_student_not_linked_to_any_institution(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test error when student not linked to any institution."""
        service = InstitutionService(db_session)
        
        # Ensure student not linked
        student_user.institution_id = None
        db_session.commit()
        
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.remove_student(institution_with_subscription.id, student_user.id)
        
        assert "not linked" in str(exc_info.value).lower()

    def test_student_linked_to_different_institution(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test error when student linked to different institution."""
        service = InstitutionService(db_session)
        
        # Create another institution
        other_institution = Institution(
            name="Other Institution",
            contact_phone="9876543210",
            subscription_status="active",
            registered_at=datetime.utcnow(),
        )
        db_session.add(other_institution)
        db_session.commit()
        
        # Link student to other institution
        student_user.institution_id = other_institution.id
        student_user.student_subtype = "institution_linked"
        db_session.commit()
        
        # Attempt to remove from first institution should fail
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.remove_student(institution_with_subscription.id, student_user.id)
        
        assert "not linked to institution" in str(exc_info.value).lower()

    def test_subtype_transition_dual_to_direct(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test subtype transition from dual to direct_subscriber."""
        service = InstitutionService(db_session)
        
        # Set student as dual
        student_user.institution_id = institution_with_subscription.id
        student_user.student_subtype = "dual"
        db_session.commit()
        
        # Remove student
        service.remove_student(institution_with_subscription.id, student_user.id)
        
        # Verify subtype reverted to direct_subscriber
        db_session.refresh(student_user)
        assert student_user.student_subtype == "direct_subscriber"
        assert student_user.institution_id is None

    def test_subtype_transition_institution_linked_to_none(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
        student_user: User,
    ):
        """Test subtype transition from institution_linked to None."""
        service = InstitutionService(db_session)
        
        # Set student as institution_linked
        student_user.institution_id = institution_with_subscription.id
        student_user.student_subtype = "institution_linked"
        db_session.commit()
        
        # Remove student
        service.remove_student(institution_with_subscription.id, student_user.id)
        
        # Verify subtype set to None
        db_session.refresh(student_user)
        assert student_user.student_subtype is None
        assert student_user.institution_id is None

    def test_seat_freed_after_removal(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
    ):
        """Test that seat is freed after student removal."""
        service = InstitutionService(db_session)
        
        # Fill all 10 seats
        students = []
        for i in range(10):
            student = User(
                email=f"student{i}@test.com",
                kcet_student_id=f"KCET{i}",
                display_name=f"Student {i}",
                password_hash=hash_password("password123"),
                role="student",
                student_subtype="institution_linked",
                institution_id=institution_with_subscription.id,
                created_at=datetime.utcnow(),
                failed_login_count=0,
            )
            db_session.add(student)
            students.append(student)
        db_session.commit()
        
        # Verify 10 students linked
        count = db_session.query(User).filter_by(
            institution_id=institution_with_subscription.id
        ).count()
        assert count == 10
        
        # Remove one student
        service.remove_student(institution_with_subscription.id, students[0].id)
        
        # Verify only 9 students linked now
        count = db_session.query(User).filter_by(
            institution_id=institution_with_subscription.id
        ).count()
        assert count == 9
        
        # Create new student
        new_student = User(
            email="newstudent@test.com",
            kcet_student_id="KCETNEW",
            display_name="New Student",
            password_hash=hash_password("password123"),
            role="student",
            student_subtype=None,
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(new_student)
        db_session.commit()
        
        # Should now be able to accept invitation (seat available)
        invitation = service.generate_invitation(institution_with_subscription.id)
        service.accept_invitation(invitation.code, new_student.id)
        
        # Verify new student linked
        db_session.refresh(new_student)
        assert new_student.institution_id == institution_with_subscription.id


class TestGetInstitutionStudents:
    """Test suite for get_institution_students()."""

    def test_get_students_empty(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
    ):
        """Test getting students when none are linked."""
        service = InstitutionService(db_session)
        
        students = service.get_institution_students(institution_with_subscription.id)
        
        assert students == []

    def test_get_students_multiple(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
    ):
        """Test getting multiple students linked to institution."""
        service = InstitutionService(db_session)
        
        # Create 3 students
        for i in range(3):
            student = User(
                email=f"student{i}@test.com",
                kcet_student_id=f"KCET{i}",
                display_name=f"Student {i}",
                password_hash=hash_password("password123"),
                role="student",
                student_subtype="institution_linked",
                institution_id=institution_with_subscription.id,
                created_at=datetime.utcnow(),
                failed_login_count=0,
            )
            db_session.add(student)
        db_session.commit()
        
        students = service.get_institution_students(institution_with_subscription.id)
        
        assert len(students) == 3
        assert all(s.student_subtype == "institution_linked" for s in students)
        assert all(s.email.startswith("student") for s in students)

    def test_get_students_only_from_institution(
        self,
        db_session: Session,
        institution_with_subscription: Institution,
    ):
        """Test that only students from specified institution are returned."""
        service = InstitutionService(db_session)
        
        # Create another institution
        other_institution = Institution(
            name="Other Institution",
            contact_phone="9876543210",
            subscription_status="active",
            registered_at=datetime.utcnow(),
        )
        db_session.add(other_institution)
        db_session.commit()
        
        # Create students for first institution
        for i in range(2):
            student = User(
                email=f"student{i}@test.com",
                kcet_student_id=f"KCET{i}",
                display_name=f"Student {i}",
                password_hash=hash_password("password123"),
                role="student",
                student_subtype="institution_linked",
                institution_id=institution_with_subscription.id,
                created_at=datetime.utcnow(),
                failed_login_count=0,
            )
            db_session.add(student)
        
        # Create students for other institution
        for i in range(3):
            student = User(
                email=f"other{i}@test.com",
                kcet_student_id=f"OTHER{i}",
                display_name=f"Other {i}",
                password_hash=hash_password("password123"),
                role="student",
                student_subtype="institution_linked",
                institution_id=other_institution.id,
                created_at=datetime.utcnow(),
                failed_login_count=0,
            )
            db_session.add(student)
        db_session.commit()
        
        # Get students for first institution
        students = service.get_institution_students(institution_with_subscription.id)
        
        assert len(students) == 2
        assert all(s.email.startswith("student") for s in students)
        assert all(s.kcet_student_id.startswith("KCET") for s in students)
