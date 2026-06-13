"""Integration tests for institution service and API routes.

Tests the complete institution workflow including:
- Institution registration
- Invitation generation and acceptance
- Student management
- Subscription plan activation
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from smartkcet.institution.service import (
    InstitutionService,
    ValidationError,
    DuplicateEmailError,
    InstitutionServiceError,
)
from smartkcet.institution.models import InstitutionRegistrationData
from smartkcet.db.models import User
from smartkcet.db.subscription_models import (
    Institution,
    Invitation,
    SubscriptionPlan,
    Subscription,
)


class TestInstitutionRegistration:
    """Test institution registration functionality."""

    def test_register_institution_success(self, db_session):
        """Test successful institution registration."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.edu",
            admin_password="Password123",
            contact_phone="1234567890",
        )
        
        result = service.register_institution(data)
        
        assert result.institution_id is not None
        assert result.admin_user_id is not None
        assert result.institution_name == "Test Institution"
        assert result.admin_email == "admin@test.edu"
        
        # Verify institution was created
        institution = (
            db_session.query(Institution)
            .filter(Institution.id == result.institution_id)
            .first()
        )
        assert institution is not None
        assert institution.name == "Test Institution"
        assert institution.subscription_status == "inactive"
        
        # Verify admin user was created
        admin_user = (
            db_session.query(User)
            .filter(User.id == result.admin_user_id)
            .first()
        )
        assert admin_user is not None
        assert admin_user.role == "institution_admin"
        assert admin_user.institution_id == result.institution_id

    def test_register_institution_duplicate_email(self, db_session):
        """Test that duplicate email is rejected."""
        service = InstitutionService(db_session)
        
        # Create first institution
        data1 = InstitutionRegistrationData(
            name="Institution 1",
            admin_email="admin@test.edu",
            admin_password="Password123",
            contact_phone="1234567890",
        )
        service.register_institution(data1)
        
        # Try to create second institution with same email
        data2 = InstitutionRegistrationData(
            name="Institution 2",
            admin_email="admin@test.edu",
            admin_password="Password456",
            contact_phone="0987654321",
        )
        
        with pytest.raises(DuplicateEmailError):
            service.register_institution(data2)

    def test_register_institution_validation_errors(self, db_session):
        """Test validation error handling."""
        service = InstitutionService(db_session)
        
        # Test invalid name (too long)
        data = InstitutionRegistrationData(
            name="A" * 101,  # Exceeds 100 character limit
            admin_email="admin@test.edu",
            admin_password="Password123",
            contact_phone="1234567890",
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        assert exc_info.value.field == "name"


class TestInvitationFlow:
    """Test invitation generation and acceptance."""

    def test_generate_invitation(self, db_session, sample_institution):
        """Test invitation code generation."""
        service = InstitutionService(db_session)
        
        result = service.generate_invitation(sample_institution.id)
        
        assert result.id is not None
        assert len(result.code) >= 32
        assert result.institution_id == sample_institution.id
        assert result.status == "pending"
        assert result.expires_at > datetime.utcnow()
        
        # Verify invitation was created in DB
        invitation = (
            db_session.query(Invitation)
            .filter(Invitation.id == result.id)
            .first()
        )
        assert invitation is not None
        assert invitation.code == result.code

    def test_generate_invitation_max_pending_limit(self, db_session, sample_institution):
        """Test that max 50 pending invitations are enforced."""
        service = InstitutionService(db_session)
        
        # Create 50 pending invitations
        for _ in range(50):
            service.generate_invitation(sample_institution.id)
        
        # 51st invitation should fail
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.generate_invitation(sample_institution.id)
        assert "Maximum pending invitations" in str(exc_info.value)

    def test_accept_invitation_success(
        self, db_session, sample_institution, sample_student, sample_institution_plan
    ):
        """Test successful invitation acceptance."""
        service = InstitutionService(db_session)
        
        # Activate institution subscription first
        subscription = Subscription(
            institution_id=sample_institution.id,
            plan_id=sample_institution_plan.id,
            status="active",
            start_date=datetime.utcnow(),
            current_period_start=datetime.utcnow(),
            next_renewal_date=datetime.utcnow() + timedelta(days=30),
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Generate invitation
        invitation = service.generate_invitation(sample_institution.id)
        
        # Accept invitation
        service.accept_invitation(invitation.code, sample_student.id)
        
        # Verify student is linked to institution
        db_session.refresh(sample_student)
        assert sample_student.institution_id == sample_institution.id
        assert sample_student.student_subtype == "institution_linked"
        
        # Verify invitation is consumed
        db_session.refresh(invitation)
        inv = db_session.query(Invitation).filter(Invitation.id == invitation.id).first()
        assert inv.status == "consumed"
        assert inv.consumed_by == sample_student.id


class TestStudentManagement:
    """Test student management operations."""

    def test_remove_student(
        self, db_session, sample_institution, sample_student
    ):
        """Test removing a student from institution."""
        service = InstitutionService(db_session)
        
        # Link student to institution first
        sample_student.institution_id = sample_institution.id
        sample_student.student_subtype = "institution_linked"
        db_session.commit()
        
        # Remove student
        service.remove_student(sample_institution.id, sample_student.id)
        
        # Verify student is unlinked
        db_session.refresh(sample_student)
        assert sample_student.institution_id is None
        assert sample_student.student_subtype is None

    def test_get_institution_students(
        self, db_session, sample_institution
    ):
        """Test listing institution students."""
        service = InstitutionService(db_session)
        
        # Create some students linked to institution
        for i in range(3):
            student = User(
                email=f"student{i}@test.edu",
                kcet_student_id=f"KCET{i:04d}",
                display_name=f"Student {i}",
                password_hash="hash",
                role="student",
                student_subtype="institution_linked",
                institution_id=sample_institution.id,
                created_at=datetime.utcnow(),
            )
            db_session.add(student)
        db_session.commit()
        
        # Get students
        students = service.get_institution_students(sample_institution.id)
        
        assert len(students) == 3
        assert all(s.student_subtype == "institution_linked" for s in students)


class TestSubscriptionPlanManagement:
    """Test institution subscription plan management."""

    def test_activate_institution_plan(
        self, db_session, sample_institution, sample_institution_plan
    ):
        """Test activating an institution subscription plan."""
        service = InstitutionService(db_session)
        
        subscription = service.activate_institution_plan(
            sample_institution.id, sample_institution_plan.id
        )
        
        assert subscription.id is not None
        assert subscription.institution_id == sample_institution.id
        assert subscription.plan_id == sample_institution_plan.id
        assert subscription.status == "active"
        assert subscription.next_renewal_date is not None
        
        # Verify institution status updated
        db_session.refresh(sample_institution)
        assert sample_institution.subscription_status == "active"

    def test_activate_institution_plan_with_existing_active(
        self, db_session, sample_institution, sample_institution_plan
    ):
        """Test that activating a plan with existing active subscription fails."""
        service = InstitutionService(db_session)
        
        # Activate first plan
        service.activate_institution_plan(
            sample_institution.id, sample_institution_plan.id
        )
        
        # Try to activate another plan
        with pytest.raises(InstitutionServiceError) as exc_info:
            service.activate_institution_plan(
                sample_institution.id, sample_institution_plan.id
            )
        assert "already has an active subscription" in str(exc_info.value)


# Fixtures

@pytest.fixture
def sample_institution(db_session):
    """Create a sample institution."""
    institution = Institution(
        name="Test Institution",
        contact_phone="1234567890",
        subscription_status="inactive",
        registered_at=datetime.utcnow(),
    )
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    return institution


@pytest.fixture
def sample_student(db_session):
    """Create a sample student."""
    student = User(
        email="student@test.edu",
        kcet_student_id="KCET0001",
        display_name="Test Student",
        password_hash="hash",
        role="student",
        student_subtype=None,
        institution_id=None,
        created_at=datetime.utcnow(),
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)
    return student


@pytest.fixture
def sample_institution_plan(db_session):
    """Create a sample institution subscription plan."""
    plan = SubscriptionPlan(
        name="Institution Basic",
        plan_type="institution",
        billing_period="monthly",
        price=1000.00,
        max_test_attempts_per_period=None,  # Unlimited
        max_student_seats=100,
        feature_flags={},
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan
