"""Tests for institution admin content management.

Tests Task 10.2 implementation:
- Institution-scoped file upload
- Institution-scoped question bank generation
- Institution-scoped exam creation
- Institution-scoped analytics
- Subscription status checks
- File validation (size, type, batch limits)
"""

import io
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import Exam, Question, Subject, Submission, User
from smartkcet.db.subscription_models import Institution, Subscription, SubscriptionPlan
from smartkcet.institution.content import (
    MAX_FILE_SIZE_BYTES,
    MAX_FILES_PER_BATCH,
    QUESTIONS_PER_EXAM,
    check_subscription_active,
    create_institution_exam,
    get_institution_content_analytics,
    list_institution_exams,
    upload_institution_content,
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
def institution_with_active_subscription(db_session):
    """Create an institution with an active subscription."""
    # Create institution
    institution = Institution(
        id=uuid.uuid4(),
        name="Test Institution",
        contact_phone="1234567890",
        subscription_status="active",
    )
    db_session.add(institution)
    
    # Create subscription plan
    plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Institution Plan",
        plan_type="institution",
        billing_period="monthly",
        price=1000.00,
        max_test_attempts_per_period=None,  # Unlimited
        max_student_seats=100,
        feature_flags={},
    )
    db_session.add(plan)
    
    # Create active subscription
    subscription = Subscription(
        id=uuid.uuid4(),
        institution_id=institution.id,
        plan_id=plan.id,
        status="active",
        start_date=datetime.utcnow(),
        current_period_start=datetime.utcnow(),
        next_renewal_date=datetime.utcnow() + timedelta(days=30),
    )
    db_session.add(subscription)
    db_session.commit()
    
    return institution


@pytest.fixture
def institution_with_inactive_subscription(db_session):
    """Create an institution with an inactive subscription."""
    institution = Institution(
        id=uuid.uuid4(),
        name="Inactive Institution",
        contact_phone="1234567890",
        subscription_status="inactive",
    )
    db_session.add(institution)
    db_session.commit()
    
    return institution


@pytest.fixture
def institution_admin_payload(institution_with_active_subscription):
    """Create a JWT payload for an institution admin."""
    return {
        "sub": str(uuid.uuid4()),
        "role": "institution_admin",
        "institution_id": str(institution_with_active_subscription.id),
    }


class TestSubscriptionChecks:
    """Test subscription status checks."""
    
    def test_check_subscription_active_returns_true_for_active(
        self, db_session, institution_with_active_subscription
    ):
        """Active subscription should return True."""
        result = check_subscription_active(db_session, institution_with_active_subscription.id)
        assert result is True
    
    def test_check_subscription_active_returns_false_for_inactive(
        self, db_session, institution_with_inactive_subscription
    ):
        """Inactive subscription should return False."""
        result = check_subscription_active(db_session, institution_with_inactive_subscription.id)
        assert result is False
    
    def test_check_subscription_active_returns_false_for_nonexistent(
        self, db_session
    ):
        """Nonexistent institution should return False."""
        result = check_subscription_active(db_session, uuid.uuid4())
        assert result is False


class TestFileUpload:
    """Test institution-scoped file upload."""
    
    @pytest.mark.asyncio
    async def test_upload_blocks_when_subscription_inactive(
        self, db_session, institution_with_inactive_subscription
    ):
        """Upload should be blocked when subscription is inactive."""
        from fastapi import HTTPException
        
        payload = {
            "sub": str(uuid.uuid4()),
            "role": "institution_admin",
            "institution_id": str(institution_with_inactive_subscription.id),
        }
        
        # Create a mock file
        file_content = b"Test content"
        mock_file = UploadFile(
            filename="test.txt",
            file=io.BytesIO(file_content),
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await upload_institution_content(
                subject="Biology",
                files=[mock_file],
                payload=payload,
                db=db_session,
            )
        
        assert exc_info.value.status_code == 403
        assert "subscription_inactive" in str(exc_info.value.detail)
    
    @pytest.mark.asyncio
    async def test_upload_rejects_files_exceeding_size_limit(
        self, db_session, institution_admin_payload
    ):
        """Upload should reject files exceeding 20MB."""
        # Create a file larger than MAX_FILE_SIZE_BYTES
        large_content = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        mock_file = UploadFile(
            filename="large.txt",
            file=io.BytesIO(large_content),
        )
        
        with patch("smartkcet.institution.content._extract_text", return_value="text"):
            result = await upload_institution_content(
                subject="Biology",
                files=[mock_file],
                payload=institution_admin_payload,
                db=db_session,
            )
        
        assert result["indexed_files"] == 0
        assert len(result["warnings"]) > 0
        assert "20MB" in result["warnings"][0]
    
    @pytest.mark.asyncio
    async def test_upload_rejects_batch_exceeding_file_limit(
        self, db_session, institution_admin_payload
    ):
        """Upload should reject batches with more than 10 files."""
        # Create 11 files
        files = [
            UploadFile(filename=f"test{i}.txt", file=io.BytesIO(b"content"))
            for i in range(MAX_FILES_PER_BATCH + 1)
        ]
        
        result = await upload_institution_content(
            subject="Biology",
            files=files,
            payload=institution_admin_payload,
            db=db_session,
        )
        
        # Result is a JSONResponse object
        assert result.status_code == 400
        import json
        body = json.loads(result.body.decode())
        assert body["error"] == "validation_error"
        assert str(MAX_FILES_PER_BATCH) in body["message"]
    
    @pytest.mark.asyncio
    async def test_upload_rejects_unsupported_file_types(
        self, db_session, institution_admin_payload
    ):
        """Upload should reject unsupported file types."""
        mock_file = UploadFile(
            filename="test.exe",
            file=io.BytesIO(b"content"),
        )
        
        result = await upload_institution_content(
            subject="Biology",
            files=[mock_file],
            payload=institution_admin_payload,
            db=db_session,
        )
        
        assert result["indexed_files"] == 0
        assert len(result["warnings"]) > 0
        assert "unsupported" in result["warnings"][0].lower()


class TestExamCreation:
    """Test institution-scoped exam creation."""
    
    def test_create_exam_blocks_when_subscription_inactive(
        self, db_session, institution_with_inactive_subscription
    ):
        """Exam creation should be blocked when subscription is inactive."""
        from fastapi import HTTPException
        
        payload = {
            "sub": str(uuid.uuid4()),
            "role": "institution_admin",
            "institution_id": str(institution_with_inactive_subscription.id),
        }
        
        with pytest.raises(HTTPException) as exc_info:
            create_institution_exam(
                subject="Biology",
                exam_name="Test Exam",
                payload=payload,
                session=db_session,
            )
        
        assert exc_info.value.status_code == 403
        assert "subscription_inactive" in str(exc_info.value.detail)
    
    def test_create_exam_requires_sufficient_questions(
        self, db_session, institution_admin_payload, institution_with_active_subscription
    ):
        """Exam creation should require at least 80 questions."""
        # Create only 50 questions (insufficient)
        for i in range(50):
            question = Question(
                subject="Biology",
                question_text=f"Question {i}",
                options=["A", "B", "C", "D"],
                correct_option="0",
                topic="General",
                generation_batch_id=uuid.uuid4(),
                institution_id=institution_with_active_subscription.id,
            )
            db_session.add(question)
        db_session.commit()
        
        result = create_institution_exam(
            subject="Biology",
            exam_name="Test Exam",
            payload=institution_admin_payload,
            session=db_session,
        )
        
        assert result.status_code == 422
        assert "insufficient_questions" in result.body.decode()
    
    def test_create_exam_succeeds_with_sufficient_questions(
        self, db_session, institution_admin_payload, institution_with_active_subscription
    ):
        """Exam creation should succeed with 80+ questions."""
        # Create 80 questions
        for i in range(QUESTIONS_PER_EXAM):
            question = Question(
                subject="Biology",
                question_text=f"Question {i}",
                options=["A", "B", "C", "D"],
                correct_option="0",
                topic="General",
                generation_batch_id=uuid.uuid4(),
                institution_id=institution_with_active_subscription.id,
            )
            db_session.add(question)
        db_session.commit()
        
        result = create_institution_exam(
            subject="Biology",
            exam_name="Test Exam",
            payload=institution_admin_payload,
            session=db_session,
        )
        
        assert "exam_id" in result
        assert result["subject"] == "Biology"
        assert result["exam_name"] == "Test Exam"
        assert len(result["set_ids"]) == 4
        
        # Verify exam is scoped to institution
        exam = db_session.query(Exam).filter(Exam.id == uuid.UUID(result["exam_id"])).first()
        assert exam is not None
        assert exam.institution_id == institution_with_active_subscription.id
    
    def test_list_exams_returns_only_institution_exams(
        self, db_session, institution_admin_payload, institution_with_active_subscription
    ):
        """List exams should return only exams for the institution."""
        # Create exam for this institution
        exam1 = Exam(
            subject="Biology",
            exam_name="Institution Exam",
            institution_id=institution_with_active_subscription.id,
        )
        db_session.add(exam1)
        
        # Create exam for another institution
        other_institution = Institution(
            id=uuid.uuid4(),
            name="Other Institution",
            contact_phone="9876543210",
            subscription_status="active",
        )
        db_session.add(other_institution)
        
        exam2 = Exam(
            subject="Biology",
            exam_name="Other Exam",
            institution_id=other_institution.id,
        )
        db_session.add(exam2)
        
        # Create platform-wide exam (no institution_id)
        exam3 = Exam(
            subject="Biology",
            exam_name="Platform Exam",
            institution_id=None,
        )
        db_session.add(exam3)
        
        db_session.commit()
        
        result = list_institution_exams(
            subject=None,
            payload=institution_admin_payload,
            session=db_session,
        )
        
        assert result["total"] == 1
        assert result["exams"][0]["exam_name"] == "Institution Exam"


class TestInstitutionAnalytics:
    """Test institution-scoped analytics."""
    
    @pytest.mark.asyncio
    async def test_analytics_returns_only_institution_students(
        self, db_session, institution_admin_payload, institution_with_active_subscription
    ):
        """Analytics should return only students linked to the institution."""
        # Create student linked to this institution
        student1 = User(
            id=uuid.uuid4(),
            email="student1@test.com",
            kcet_student_id="KCET001",
            display_name="Student 1",
            password_hash="hash",
            role="student",
            student_subtype="institution_linked",
            institution_id=institution_with_active_subscription.id,
        )
        db_session.add(student1)
        
        # Create student linked to another institution
        other_institution = Institution(
            id=uuid.uuid4(),
            name="Other Institution",
            contact_phone="9876543210",
            subscription_status="active",
        )
        db_session.add(other_institution)
        
        student2 = User(
            id=uuid.uuid4(),
            email="student2@test.com",
            kcet_student_id="KCET002",
            display_name="Student 2",
            password_hash="hash",
            role="student",
            student_subtype="institution_linked",
            institution_id=other_institution.id,
        )
        db_session.add(student2)
        
        db_session.commit()
        
        result = await get_institution_content_analytics(
            payload=institution_admin_payload,
            db=db_session,
        )
        
        assert result["total_students"] == 1
        assert result["students"][0]["display_name"] == "Student 1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
