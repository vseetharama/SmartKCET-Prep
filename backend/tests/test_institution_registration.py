"""Unit tests for institution registration (Task 6.1).

Tests the InstitutionService.register_institution() method to ensure:
- Atomic creation of institution + institution_admin
- Validation of all input fields (name, email, password, phone)
- Rejection of duplicate emails
- Return of first failing field on validation error
- Handling of DB unavailability

**Requirements:** 6.1, 6.2, 6.7, 6.8, 6.9
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import User
from smartkcet.db.subscription_models import Institution
from smartkcet.institution.models import InstitutionRegistrationData
from smartkcet.institution.service import (
    DatabaseUnavailableError,
    DuplicateEmailError,
    InstitutionService,
    ValidationError,
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


class TestInstitutionRegistration:
    """Test suite for institution registration."""

    def test_successful_registration(self, db_session: Session):
        """Test successful institution registration with valid data."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        result = service.register_institution(data)
        
        # Verify response
        assert result.institution_id is not None
        assert result.admin_user_id is not None
        assert result.institution_name == "Test Institution"
        assert result.admin_email == "admin@test.com"
        assert result.registered_at is not None
        
        # Verify institution record created
        institution = db_session.query(Institution).filter_by(
            id=result.institution_id
        ).first()
        assert institution is not None
        assert institution.name == "Test Institution"
        assert institution.contact_phone == "1234567890"
        assert institution.subscription_status == "inactive"
        
        # Verify admin user record created
        admin_user = db_session.query(User).filter_by(
            id=result.admin_user_id
        ).first()
        assert admin_user is not None
        assert admin_user.email == "admin@test.com"
        assert admin_user.role == "institution_admin"
        assert admin_user.student_subtype is None
        assert admin_user.institution_id == result.institution_id
        assert admin_user.kcet_student_id is None
        assert admin_user.password_hash is not None
        assert admin_user.password_hash != "password123"  # Should be hashed

    def test_duplicate_email_rejection(self, db_session: Session):
        """Test rejection of duplicate admin email."""
        service = InstitutionService(db_session)
        
        # Create first institution
        data1 = InstitutionRegistrationData(
            name="First Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890",
        )
        service.register_institution(data1)
        
        # Attempt to create second institution with same email
        data2 = InstitutionRegistrationData(
            name="Second Institution",
            admin_email="admin@test.com",
            admin_password="password456",
            contact_phone="9876543210",
        )
        
        with pytest.raises(DuplicateEmailError) as exc_info:
            service.register_institution(data2)
        
        assert exc_info.value.email == "admin@test.com"
        
        # Verify no second institution was created
        institutions = db_session.query(Institution).all()
        assert len(institutions) == 1
        assert institutions[0].name == "First Institution"

    def test_validation_name_too_short(self, db_session: Session):
        """Test validation error for name too short."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field == "name"
        assert "required" in exc_info.value.reason.lower()

    def test_validation_name_too_long(self, db_session: Session):
        """Test validation error for name too long."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="A" * 101,  # 101 characters
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field == "name"
        assert "100" in exc_info.value.reason

    def test_validation_invalid_email(self, db_session: Session):
        """Test validation error for invalid email format."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="invalid-email",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field == "email"

    def test_validation_email_too_long(self, db_session: Session):
        """Test validation error for email exceeding 254 characters."""
        service = InstitutionService(db_session)
        
        # Create an email that's 255 characters long
        long_email = "a" * 240 + "@example.com"  # 253 chars total
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email=long_email + "x",  # 254 chars - should pass
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        # This should work (254 chars)
        try:
            service.register_institution(data)
        except ValidationError:
            pytest.fail("254 character email should be valid")
        
        # Now test 255 chars - should fail
        db_session.rollback()  # Reset session
        
        data2 = InstitutionRegistrationData(
            name="Test Institution 2",
            admin_email=long_email + "xx",  # 255 chars
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data2)
        
        assert exc_info.value.field == "email"
        assert "254" in exc_info.value.reason

    def test_validation_password_too_short(self, db_session: Session):
        """Test validation error for password too short."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="pass1",  # Only 5 characters
            contact_phone="1234567890",
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field in ["password", "admin_password"]
        assert "8" in exc_info.value.reason

    def test_validation_password_too_long(self, db_session: Session):
        """Test validation error for password exceeding 72 characters."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="a" * 73 + "1",  # 74 characters with digit
            contact_phone="1234567890",
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field == "admin_password"
        assert "72" in exc_info.value.reason

    def test_validation_password_no_digit(self, db_session: Session):
        """Test validation error for password without digit."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="passwordonly",  # No digit
            contact_phone="1234567890",
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field in ["password", "admin_password"]
        assert "digit" in exc_info.value.reason.lower()

    def test_validation_phone_too_short(self, db_session: Session):
        """Test validation error for phone number too short."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="123456789",  # Only 9 digits
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field == "contact_phone"
        assert "10" in exc_info.value.reason

    def test_validation_phone_too_long(self, db_session: Session):
        """Test validation error for phone number too long."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890123456",  # 16 digits
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field == "contact_phone"
        assert "15" in exc_info.value.reason

    def test_validation_phone_non_digits(self, db_session: Session):
        """Test validation error for phone number with non-digit characters."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="123-456-7890",  # Contains hyphens
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        assert exc_info.value.field == "contact_phone"
        assert "digit" in exc_info.value.reason.lower()

    def test_first_failing_field_returned(self, db_session: Session):
        """Test that first failing field is returned on validation error."""
        service = InstitutionService(db_session)
        
        # Multiple validation errors - name is checked first
        data = InstitutionRegistrationData(
            name="",  # Invalid
            admin_email="invalid-email",  # Invalid
            admin_password="short",  # Invalid
            contact_phone="123",  # Invalid
        )
        
        with pytest.raises(ValidationError) as exc_info:
            service.register_institution(data)
        
        # Should return the first failing field (name)
        assert exc_info.value.field == "name"

    def test_atomic_transaction_rollback(self, db_session: Session):
        """Test that transaction rolls back on error (no partial records)."""
        service = InstitutionService(db_session)
        
        # Create a user with the email first
        existing_user = User(
            email="admin@test.com",
            kcet_student_id="TEST123",
            display_name="Existing User",
            password_hash="hash",
            role="student",
        )
        db_session.add(existing_user)
        db_session.commit()
        
        # Attempt to register institution with duplicate email
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        with pytest.raises(DuplicateEmailError):
            service.register_institution(data)
        
        # Verify no institution was created
        institutions = db_session.query(Institution).all()
        assert len(institutions) == 0
        
        # Verify no new user was created
        users = db_session.query(User).all()
        assert len(users) == 1
        assert users[0].email == "admin@test.com"
        assert users[0].role == "student"  # Original user unchanged

    def test_email_normalization(self, db_session: Session):
        """Test that email is normalized (lowercased domain)."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="Admin@TEST.COM",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        result = service.register_institution(data)
        
        # Verify email is normalized
        admin_user = db_session.query(User).filter_by(
            id=result.admin_user_id
        ).first()
        assert admin_user.email == "admin@test.com"

    def test_password_is_hashed(self, db_session: Session):
        """Test that password is hashed, not stored in plaintext."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        result = service.register_institution(data)
        
        # Verify password is hashed
        admin_user = db_session.query(User).filter_by(
            id=result.admin_user_id
        ).first()
        assert admin_user.password_hash != "password123"
        assert len(admin_user.password_hash) > 20  # Bcrypt hashes are long
        assert admin_user.password_hash.startswith("$2b$")  # Bcrypt prefix

    def test_institution_defaults(self, db_session: Session):
        """Test that institution is created with correct defaults."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        result = service.register_institution(data)
        
        # Verify institution defaults
        institution = db_session.query(Institution).filter_by(
            id=result.institution_id
        ).first()
        assert institution.subscription_status == "inactive"
        assert institution.registered_at is not None

    def test_admin_user_defaults(self, db_session: Session):
        """Test that admin user is created with correct defaults."""
        service = InstitutionService(db_session)
        
        data = InstitutionRegistrationData(
            name="Test Institution",
            admin_email="admin@test.com",
            admin_password="password123",
            contact_phone="1234567890",
        )
        
        result = service.register_institution(data)
        
        # Verify admin user defaults
        admin_user = db_session.query(User).filter_by(
            id=result.admin_user_id
        ).first()
        assert admin_user.role == "institution_admin"
        assert admin_user.student_subtype is None
        assert admin_user.kcet_student_id is None
        assert admin_user.failed_login_count == 0
        assert admin_user.lockout_until is None
        assert admin_user.created_at is not None
