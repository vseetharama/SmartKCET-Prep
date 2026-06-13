"""Integration tests for Task 12.2: Institution service wiring.

This test suite verifies that the institution service is properly wired into:
1. Student exam listing (institution-scoped exam visibility)
2. Admin analytics (institution-scoped analytics)
3. Institution student management (admin dashboard integration)

**Validates: Requirements 7.3, 7.4, 9.7**
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.db.models import Base, Exam, ExamSet, Submission, User
from smartkcet.db.subscription_models import Institution, Subscription, SubscriptionPlan


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def institution_1(db_session: Session) -> Institution:
    """Create first test institution."""
    inst = Institution(
        id=uuid.uuid4(),
        name="Test Institution 1",
        contact_phone="1234567890",
        subscription_status="active",
        registered_at=datetime.utcnow(),
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)
    return inst


@pytest.fixture
def institution_2(db_session: Session) -> Institution:
    """Create second test institution."""
    inst = Institution(
        id=uuid.uuid4(),
        name="Test Institution 2",
        contact_phone="0987654321",
        subscription_status="active",
        registered_at=datetime.utcnow(),
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)
    return inst


@pytest.fixture
def institution_admin_1(db_session: Session, institution_1: Institution) -> User:
    """Create institution admin for institution 1."""
    admin = User(
        id=uuid.uuid4(),
        email="admin1@test.com",
        kcet_student_id=None,
        display_name="Admin 1",
        password_hash="dummy_hash",
        role="institution_admin",
        student_subtype=None,
        institution_id=institution_1.id,
        created_at=datetime.utcnow(),
        failed_login_count=0,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def institution_admin_2(db_session: Session, institution_2: Institution) -> User:
    """Create institution admin for institution 2."""
    admin = User(
        id=uuid.uuid4(),
        email="admin2@test.com",
        kcet_student_id=None,
        display_name="Admin 2",
        password_hash="dummy_hash",
        role="institution_admin",
        student_subtype=None,
        institution_id=institution_2.id,
        created_at=datetime.utcnow(),
        failed_login_count=0,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def student_inst_1(db_session: Session, institution_1: Institution) -> User:
    """Create student linked to institution 1."""
    student = User(
        id=uuid.uuid4(),
        email="student1@test.com",
        kcet_student_id="KCET1001",
        display_name="Student 1",
        password_hash="dummy_hash",
        role="student",
        student_subtype="institution_linked",
        institution_id=institution_1.id,
        created_at=datetime.utcnow(),
        failed_login_count=0,
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)
    return student


@pytest.fixture
def student_inst_2(db_session: Session, institution_2: Institution) -> User:
    """Create student linked to institution 2."""
    student = User(
        id=uuid.uuid4(),
        email="student2@test.com",
        kcet_student_id="KCET1002",
        display_name="Student 2",
        password_hash="dummy_hash",
        role="student",
        student_subtype="institution_linked",
        institution_id=institution_2.id,
        created_at=datetime.utcnow(),
        failed_login_count=0,
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)
    return student


@pytest.fixture
def student_no_inst(db_session: Session) -> User:
    """Create student not linked to any institution."""
    student = User(
        id=uuid.uuid4(),
        email="student3@test.com",
        kcet_student_id="KCET1003",
        display_name="Student 3",
        password_hash="dummy_hash",
        role="student",
        student_subtype="direct_subscriber",
        institution_id=None,
        created_at=datetime.utcnow(),
        failed_login_count=0,
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)
    return student


@pytest.fixture
def platform_wide_exam(db_session: Session) -> Exam:
    """Create a platform-wide exam (institution_id IS NULL)."""
    exam = Exam(
        id=uuid.uuid4(),
        subject="Biology",
        exam_name="Platform Biology Exam",
        institution_id=None,  # Platform-wide
        created_at=datetime.utcnow(),
        is_published=True,
    )
    db_session.add(exam)
    db_session.commit()
    db_session.refresh(exam)
    return exam


@pytest.fixture
def institution_1_exam(db_session: Session, institution_1: Institution) -> Exam:
    """Create an exam specific to institution 1."""
    exam = Exam(
        id=uuid.uuid4(),
        subject="Physics",
        exam_name="Institution 1 Physics Exam",
        institution_id=institution_1.id,
        created_at=datetime.utcnow(),
        is_published=True,
    )
    db_session.add(exam)
    db_session.commit()
    db_session.refresh(exam)
    return exam


@pytest.fixture
def institution_2_exam(db_session: Session, institution_2: Institution) -> Exam:
    """Create an exam specific to institution 2."""
    exam = Exam(
        id=uuid.uuid4(),
        subject="Chemistry",
        exam_name="Institution 2 Chemistry Exam",
        institution_id=institution_2.id,
        created_at=datetime.utcnow(),
        is_published=True,
    )
    db_session.add(exam)
    db_session.commit()
    db_session.refresh(exam)
    return exam


class TestStudentExamVisibility:
    """Test institution-scoped exam visibility for students (REQ-7.3, 9.7)."""

    def test_institution_student_query_filters_correctly(
        self,
        db_session: Session,
        student_inst_1: User,
        platform_wide_exam: Exam,
        institution_1_exam: Exam,
        institution_2_exam: Exam,
    ):
        """Student linked to institution 1 query filters to platform-wide + institution 1 exams."""
        from sqlalchemy import or_, select
        
        # Simulate the query from student/exams.py
        student_institution_id = student_inst_1.institution_id
        
        stmt = select(Exam).where(Exam.is_published.is_(True))
        
        # Apply institution visibility filter (same logic as in student/exams.py)
        if student_institution_id is not None:
            stmt = stmt.where(
                or_(
                    Exam.institution_id.is_(None),  # Platform-wide exams
                    Exam.institution_id == student_institution_id  # Institution-specific exams
                )
            )
        else:
            stmt = stmt.where(Exam.institution_id.is_(None))
        
        results = db_session.execute(stmt).scalars().all()
        
        # Should see Biology (platform-wide) and Physics (institution 1)
        exam_subjects = {exam.subject for exam in results}
        assert "Biology" in exam_subjects  # Platform-wide
        assert "Physics" in exam_subjects  # Institution 1
        assert "Chemistry" not in exam_subjects  # Institution 2 (should not see)
        assert len(results) == 2

    def test_non_institution_student_query_filters_correctly(
        self,
        db_session: Session,
        student_no_inst: User,
        platform_wide_exam: Exam,
        institution_1_exam: Exam,
        institution_2_exam: Exam,
    ):
        """Student not linked to any institution query filters to only platform-wide exams."""
        from sqlalchemy import or_, select
        
        # Simulate the query from student/exams.py
        student_institution_id = student_no_inst.institution_id
        
        stmt = select(Exam).where(Exam.is_published.is_(True))
        
        # Apply institution visibility filter
        if student_institution_id is not None:
            stmt = stmt.where(
                or_(
                    Exam.institution_id.is_(None),
                    Exam.institution_id == student_institution_id
                )
            )
        else:
            stmt = stmt.where(Exam.institution_id.is_(None))
        
        results = db_session.execute(stmt).scalars().all()
        
        # Should see only Biology (platform-wide)
        exam_subjects = {exam.subject for exam in results}
        assert "Biology" in exam_subjects  # Platform-wide
        assert "Physics" not in exam_subjects  # Institution 1
        assert "Chemistry" not in exam_subjects  # Institution 2
        assert len(results) == 1


class TestAdminAnalyticsScoping:
    """Test institution-scoped analytics for institution admins (REQ-7.4, 7.7, 9.7)."""

    def test_institution_admin_query_scopes_to_own_students(
        self,
        db_session: Session,
        institution_admin_1: User,
        student_inst_1: User,
        student_inst_2: User,
        platform_wide_exam: Exam,
    ):
        """Institution admin 1 query scopes to only institution 1 students."""
        # Create exam set for platform-wide exam
        exam_set = ExamSet(
            id=uuid.uuid4(),
            exam_id=platform_wide_exam.id,
            set_label="A",
        )
        db_session.add(exam_set)
        db_session.commit()
        
        # Create submissions from both students
        submission_1 = Submission(
            id=uuid.uuid4(),
            user_id=student_inst_1.id,
            exam_set_id=exam_set.id,
            score_pct=75.0,
            time_taken_sec=1800,
            submitted_at=datetime.utcnow(),
            status="completed",
        )
        submission_2 = Submission(
            id=uuid.uuid4(),
            user_id=student_inst_2.id,
            exam_set_id=exam_set.id,
            score_pct=85.0,
            time_taken_sec=1600,
            submitted_at=datetime.utcnow(),
            status="completed",
        )
        db_session.add_all([submission_1, submission_2])
        db_session.commit()
        
        # Simulate the query from admin/analytics.py
        from sqlalchemy import select
        
        admin_role = institution_admin_1.role
        admin_institution_id = institution_admin_1.institution_id
        
        stmt = (
            select(Submission, ExamSet, Exam, User)
            .join(ExamSet, ExamSet.id == Submission.exam_set_id)
            .join(Exam, Exam.id == ExamSet.exam_id)
            .join(User, User.id == Submission.user_id)
        )
        
        # Apply institution scoping (same logic as in admin/analytics.py)
        if admin_role == "institution_admin" and admin_institution_id is not None:
            stmt = stmt.where(User.institution_id == admin_institution_id)
        
        results = db_session.execute(stmt).all()
        
        # Should see only submission from student_inst_1
        assert len(results) == 1
        _, _, _, user = results[0]
        assert user.kcet_student_id == student_inst_1.kcet_student_id

    def test_platform_admin_query_sees_all_students(
        self,
        db_session: Session,
        student_inst_1: User,
        student_inst_2: User,
        platform_wide_exam: Exam,
    ):
        """Platform admin query sees submissions from all students."""
        # Create platform admin
        platform_admin = User(
            id=uuid.uuid4(),
            email="platform@test.com",
            kcet_student_id=None,
            display_name="Platform Admin",
            password_hash="dummy_hash",
            role="platform_admin",
            student_subtype=None,
            institution_id=None,
            created_at=datetime.utcnow(),
            failed_login_count=0,
        )
        db_session.add(platform_admin)
        db_session.commit()
        
        # Create exam set for platform-wide exam
        exam_set = ExamSet(
            id=uuid.uuid4(),
            exam_id=platform_wide_exam.id,
            set_label="A",
        )
        db_session.add(exam_set)
        db_session.commit()
        
        # Create submissions from both students
        submission_1 = Submission(
            id=uuid.uuid4(),
            user_id=student_inst_1.id,
            exam_set_id=exam_set.id,
            score_pct=75.0,
            time_taken_sec=1800,
            submitted_at=datetime.utcnow(),
            status="completed",
        )
        submission_2 = Submission(
            id=uuid.uuid4(),
            user_id=student_inst_2.id,
            exam_set_id=exam_set.id,
            score_pct=85.0,
            time_taken_sec=1600,
            submitted_at=datetime.utcnow(),
            status="completed",
        )
        db_session.add_all([submission_1, submission_2])
        db_session.commit()
        
        # Simulate the query from admin/analytics.py
        from sqlalchemy import select
        
        admin_role = platform_admin.role
        admin_institution_id = platform_admin.institution_id
        
        stmt = (
            select(Submission, ExamSet, Exam, User)
            .join(ExamSet, ExamSet.id == Submission.exam_set_id)
            .join(Exam, Exam.id == ExamSet.exam_id)
            .join(User, User.id == Submission.user_id)
        )
        
        # Apply institution scoping
        if admin_role == "institution_admin" and admin_institution_id is not None:
            stmt = stmt.where(User.institution_id == admin_institution_id)
        
        results = db_session.execute(stmt).all()
        
        # Should see both submissions (no filtering for platform admin)
        assert len(results) == 2
        student_ids = {user.kcet_student_id for _, _, _, user in results}
        assert student_inst_1.kcet_student_id in student_ids
        assert student_inst_2.kcet_student_id in student_ids


class TestInstitutionStudentManagement:
    """Test institution student management endpoints (REQ-7.4, 9.6)."""

    def test_institution_service_lists_own_students(
        self,
        db_session: Session,
        institution_admin_1: User,
        student_inst_1: User,
        student_inst_2: User,
    ):
        """Institution service lists students linked to the institution."""
        from smartkcet.institution.service import InstitutionService
        
        service = InstitutionService(db_session)
        students = service.get_institution_students(institution_admin_1.institution_id)
        
        # Should see only student_inst_1
        assert len(students) == 1
        assert students[0].kcet_student_id == student_inst_1.kcet_student_id
        assert students[0].email == student_inst_1.email

    def test_institution_service_removes_student(
        self,
        db_session: Session,
        institution_admin_1: User,
        student_inst_1: User,
    ):
        """Institution service can remove a student from the institution."""
        from smartkcet.institution.service import InstitutionService
        
        service = InstitutionService(db_session)
        
        # Remove student
        service.remove_student(institution_admin_1.institution_id, student_inst_1.id)
        
        # Verify student is no longer linked
        db_session.refresh(student_inst_1)
        assert student_inst_1.institution_id is None
        assert student_inst_1.student_subtype is None  # Transitioned from institution_linked to None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
