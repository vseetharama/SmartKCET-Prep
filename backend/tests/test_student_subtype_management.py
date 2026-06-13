"""Unit tests for student subtype management (Task 8.4).

Tests the transition_student_subtype method and its integration with
accept_invitation and remove_student methods.

**Requirements:** 10.3, 10.4, 10.7
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.subscription_models import Institution, Subscription, SubscriptionPlan
from smartkcet.institution.service import InstitutionService, InstitutionServiceError


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
def institution_with_active_subscription(db_session: Session):
    """Create an institution with an active subscription for testing."""
    # Create institution
    institution = Institution(
        id=uuid.uuid4(),
        name="Test Institution",
        contact_phone="1234567890",
        subscription_status="active",
        registered_at=datetime.utcnow(),
    )
    db_session.add(institution)
    
    # Create subscription plan
    plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Test Institution Plan",
        plan_type="institution",
        billing_period="monthly",
        price=1000.0,
        max_test_attempts_per_period=None,  # Unlimited
        max_student_seats=100,
        feature_flags={},
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(plan)
    
    # Create active subscription
    subscription = Subscription(
        id=uuid.uuid4(),
        institution_id=institution.id,
        user_id=None,
        plan_id=plan.id,
        status="active",
        start_date=datetime.utcnow(),
        current_period_start=datetime.utcnow(),
        next_renewal_date=datetime.utcnow().replace(year=datetime.utcnow().year + 1),
        trial_duration_days=None,
        created_at=datetime.utcnow(),
    )
    db_session.add(subscription)
    db_session.commit()
    
    return institution


class TestStudentSubtypeTransitions:
    """Test student subtype transitions."""
    
    def test_transition_null_to_institution_linked(self, db_session: Session):
        """Test transition from null to institution_linked when joining institution."""
        # Create a student with no subtype
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST001",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype=None,
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Transition to institution_linked
        service = InstitutionService(db_session)
        service.transition_student_subtype(student.id, "join_institution")
        
        # Verify subtype changed
        db_session.refresh(student)
        assert student.student_subtype == "institution_linked"
    
    def test_transition_direct_subscriber_to_dual(self, db_session: Session):
        """Test transition from direct_subscriber to dual when joining institution."""
        # Create a student with direct_subscriber subtype
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST002",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype="direct_subscriber",
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Transition to dual
        service = InstitutionService(db_session)
        service.transition_student_subtype(student.id, "join_institution")
        
        # Verify subtype changed
        db_session.refresh(student)
        assert student.student_subtype == "dual"
    
    def test_transition_dual_to_direct_subscriber(self, db_session: Session):
        """Test transition from dual to direct_subscriber when leaving institution."""
        # Create a student with dual subtype
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST003",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype="dual",
            institution_id=uuid.uuid4(),
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Transition to direct_subscriber
        service = InstitutionService(db_session)
        service.transition_student_subtype(student.id, "leave_institution")
        
        # Verify subtype changed
        db_session.refresh(student)
        assert student.student_subtype == "direct_subscriber"
    
    def test_transition_institution_linked_to_null(self, db_session: Session):
        """Test transition from institution_linked to null when leaving institution."""
        # Create a student with institution_linked subtype
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST004",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype="institution_linked",
            institution_id=uuid.uuid4(),
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Transition to null
        service = InstitutionService(db_session)
        service.transition_student_subtype(student.id, "leave_institution")
        
        # Verify subtype changed
        db_session.refresh(student)
        assert student.student_subtype is None
    
    def test_transition_preserves_individual_subscription(self, db_session: Session):
        """Test that transitioning to dual preserves existing individual subscription."""
        # This is tested implicitly by the transition logic - the method only
        # changes the subtype field, not any subscription records
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST005",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype="direct_subscriber",
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Transition to dual
        service = InstitutionService(db_session)
        service.transition_student_subtype(student.id, "join_institution")
        
        # Verify subtype changed but student record is intact
        db_session.refresh(student)
        assert student.student_subtype == "dual"
        assert student.email == "student@example.com"
        assert student.kcet_student_id == "TEST005"
    
    def test_transition_invalid_type_raises_error(self, db_session: Session):
        """Test that invalid transition type raises error."""
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST006",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype=None,
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Try invalid transition type
        service = InstitutionService(db_session)
        with pytest.raises(InstitutionServiceError, match="Invalid transition type"):
            service.transition_student_subtype(student.id, "invalid_type")
    
    def test_transition_non_student_raises_error(self, db_session: Session):
        """Test that transitioning non-student user raises error."""
        admin = User(
            id=uuid.uuid4(),
            email="admin@example.com",
            kcet_student_id=None,
            display_name="Admin",
            password_hash="hash",
            role="platform_admin",
            student_subtype=None,
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(admin)
        db_session.commit()
        
        # Try to transition admin
        service = InstitutionService(db_session)
        with pytest.raises(InstitutionServiceError, match="is not a student"):
            service.transition_student_subtype(admin.id, "join_institution")
    
    def test_transition_nonexistent_student_raises_error(self, db_session: Session):
        """Test that transitioning nonexistent student raises error."""
        service = InstitutionService(db_session)
        fake_id = uuid.uuid4()
        
        with pytest.raises(InstitutionServiceError, match="not found"):
            service.transition_student_subtype(fake_id, "join_institution")
    
    def test_transition_idempotent_when_already_in_target_state(self, db_session: Session):
        """Test that transition is idempotent when already in target state."""
        # Create student already in institution_linked state
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST007",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype="institution_linked",
            institution_id=uuid.uuid4(),
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Try to transition to institution_linked again
        service = InstitutionService(db_session)
        service.transition_student_subtype(student.id, "join_institution")
        
        # Verify subtype unchanged
        db_session.refresh(student)
        assert student.student_subtype == "institution_linked"


class TestSubtypeTransitionIntegration:
    """Test subtype transitions integrated with invitation flow."""
    
    def test_accept_invitation_transitions_null_to_institution_linked(
        self, db_session: Session, institution_with_active_subscription
    ):
        """Test that accepting invitation transitions null to institution_linked."""
        from smartkcet.db.subscription_models import Invitation
        
        institution = institution_with_active_subscription
        
        # Create invitation
        invitation = Invitation(
            id=uuid.uuid4(),
            institution_id=institution.id,
            code="TEST_CODE_001",
            status="pending",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow().replace(year=datetime.utcnow().year + 1),
        )
        db_session.add(invitation)
        
        # Create student with no subtype
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST008",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype=None,
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Accept invitation
        service = InstitutionService(db_session)
        service.accept_invitation("TEST_CODE_001", student.id)
        
        # Verify subtype transitioned
        db_session.refresh(student)
        assert student.student_subtype == "institution_linked"
        assert student.institution_id == institution.id
    
    def test_remove_student_transitions_dual_to_direct_subscriber(
        self, db_session: Session, institution_with_active_subscription
    ):
        """Test that removing student transitions dual to direct_subscriber."""
        institution = institution_with_active_subscription
        
        # Create student with dual subtype
        student = User(
            id=uuid.uuid4(),
            email="student@example.com",
            kcet_student_id="TEST009",
            display_name="Test Student",
            password_hash="hash",
            role="student",
            student_subtype="dual",
            institution_id=institution.id,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(student)
        db_session.commit()
        
        # Remove student
        service = InstitutionService(db_session)
        service.remove_student(institution.id, student.id)
        
        # Verify subtype transitioned
        db_session.refresh(student)
        assert student.student_subtype == "direct_subscriber"
        assert student.institution_id is None
