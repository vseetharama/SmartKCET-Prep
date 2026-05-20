"""Unit tests for smartkcet.leaderboard.service module.

Tests cover:
- Subject-filtered leaderboard (REQ-11.7): only submissions for the
  specified subject are considered, and students with zero submissions
  in that subject are excluded.
- Unfiltered leaderboard: all completed submissions are considered.
- Eligibility filtering: students below 30% average or with zero
  submissions are excluded.
- Cohort stats computation and ranking.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from smartkcet.db.base import Base
from smartkcet.db.models import Exam, ExamSet, Submission, Subject, User
from smartkcet.leaderboard.service import get_leaderboard


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database with all tables for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _create_user(session: Session, display_name: str, kcet_id: str) -> uuid.UUID:
    """Helper to create a student user."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"{display_name.lower()}@test.com",
        kcet_student_id=kcet_id,
        display_name=display_name,
        password_hash="hashed",
        role="student",
    )
    session.add(user)
    session.flush()
    return user_id


def _create_exam_and_set(session: Session, subject: str) -> uuid.UUID:
    """Helper to create an exam and one exam set, returning the set ID."""
    exam_id = uuid.uuid4()
    exam = Exam(id=exam_id, subject=subject, is_published=True)
    session.add(exam)
    session.flush()

    exam_set_id = uuid.uuid4()
    exam_set = ExamSet(id=exam_set_id, exam_id=exam_id, set_label="A")
    session.add(exam_set)
    session.flush()
    return exam_set_id


def _create_submission(
    session: Session,
    user_id: uuid.UUID,
    exam_set_id: uuid.UUID,
    score_pct: float,
) -> None:
    """Helper to create a completed submission."""
    submission = Submission(
        id=uuid.uuid4(),
        user_id=user_id,
        exam_set_id=exam_set_id,
        answers={"1": "A"},
        score_pct=score_pct,
        topic_breakdown={},
        time_taken_sec=600,
        status="completed",
    )
    session.add(submission)
    session.flush()


class TestGetLeaderboardUnfiltered:
    """Tests for get_leaderboard without subject filter."""

    def test_empty_database_returns_empty(self, db_session):
        """No submissions means empty leaderboard."""
        result = get_leaderboard(db_session)
        assert result == []

    def test_single_eligible_student(self, db_session):
        """A single student with score >= 30 appears on leaderboard."""
        user_id = _create_user(db_session, "Alice", "KCET0001")
        exam_set_id = _create_exam_and_set(db_session, Subject.Biology.value)
        _create_submission(db_session, user_id, exam_set_id, 75.0)
        db_session.commit()

        result = get_leaderboard(db_session)
        assert len(result) == 1
        assert result[0].rank == 1
        assert result[0].display_name == "Alice"
        assert result[0].kcet_student_id == "KCET0001"

    def test_ineligible_student_excluded(self, db_session):
        """A student with average < 30 is excluded."""
        user_id = _create_user(db_session, "Bob", "KCET0002")
        exam_set_id = _create_exam_and_set(db_session, Subject.Physics.value)
        _create_submission(db_session, user_id, exam_set_id, 20.0)
        db_session.commit()

        result = get_leaderboard(db_session)
        assert result == []

    def test_multiple_students_ranked_correctly(self, db_session):
        """Multiple eligible students are ranked by composite score."""
        exam_set_id = _create_exam_and_set(db_session, Subject.Biology.value)

        alice_id = _create_user(db_session, "Alice", "KCET0001")
        _create_submission(db_session, alice_id, exam_set_id, 90.0)

        bob_id = _create_user(db_session, "Bob", "KCET0002")
        _create_submission(db_session, bob_id, exam_set_id, 60.0)

        charlie_id = _create_user(db_session, "Charlie", "KCET0003")
        _create_submission(db_session, charlie_id, exam_set_id, 75.0)
        db_session.commit()

        result = get_leaderboard(db_session)
        assert len(result) == 3
        assert result[0].display_name == "Alice"
        assert result[0].rank == 1
        assert result[1].display_name == "Charlie"
        assert result[1].rank == 2
        assert result[2].display_name == "Bob"
        assert result[2].rank == 3


class TestGetLeaderboardSubjectFiltered:
    """Tests for get_leaderboard with subject filter (REQ-11.7)."""

    def test_subject_filter_excludes_students_without_subject_submissions(
        self, db_session
    ):
        """Students with zero submissions in the filtered subject are excluded."""
        bio_set_id = _create_exam_and_set(db_session, Subject.Biology.value)
        phys_set_id = _create_exam_and_set(db_session, Subject.Physics.value)

        # Alice has Biology submissions only
        alice_id = _create_user(db_session, "Alice", "KCET0001")
        _create_submission(db_session, alice_id, bio_set_id, 80.0)

        # Bob has Physics submissions only
        bob_id = _create_user(db_session, "Bob", "KCET0002")
        _create_submission(db_session, bob_id, phys_set_id, 90.0)
        db_session.commit()

        # Filter by Biology: only Alice should appear
        result = get_leaderboard(db_session, subject=Subject.Biology.value)
        assert len(result) == 1
        assert result[0].display_name == "Alice"

        # Filter by Physics: only Bob should appear
        result = get_leaderboard(db_session, subject=Subject.Physics.value)
        assert len(result) == 1
        assert result[0].display_name == "Bob"

    def test_subject_filter_uses_subject_scores_for_ranking(self, db_session):
        """Ranking uses per-subject scores, not overall scores."""
        bio_set_id = _create_exam_and_set(db_session, Subject.Biology.value)
        phys_set_id = _create_exam_and_set(db_session, Subject.Physics.value)

        # Alice: high in Biology, low in Physics
        alice_id = _create_user(db_session, "Alice", "KCET0001")
        _create_submission(db_session, alice_id, bio_set_id, 95.0)
        _create_submission(db_session, alice_id, phys_set_id, 40.0)

        # Bob: low in Biology, high in Physics
        bob_id = _create_user(db_session, "Bob", "KCET0002")
        _create_submission(db_session, bob_id, bio_set_id, 50.0)
        _create_submission(db_session, bob_id, phys_set_id, 95.0)
        db_session.commit()

        # Biology filter: Alice should rank higher
        bio_result = get_leaderboard(db_session, subject=Subject.Biology.value)
        assert len(bio_result) == 2
        assert bio_result[0].display_name == "Alice"
        assert bio_result[1].display_name == "Bob"

        # Physics filter: Bob should rank higher
        phys_result = get_leaderboard(db_session, subject=Subject.Physics.value)
        assert len(phys_result) == 2
        assert phys_result[0].display_name == "Bob"
        assert phys_result[1].display_name == "Alice"

    def test_subject_filter_empty_subject_returns_empty(self, db_session):
        """A subject with no submissions returns empty leaderboard."""
        bio_set_id = _create_exam_and_set(db_session, Subject.Biology.value)

        alice_id = _create_user(db_session, "Alice", "KCET0001")
        _create_submission(db_session, alice_id, bio_set_id, 80.0)
        db_session.commit()

        # Chemistry has no submissions
        result = get_leaderboard(db_session, subject=Subject.Chemistry.value)
        assert result == []

    def test_invalid_subject_returns_empty(self, db_session):
        """An invalid subject value returns empty leaderboard."""
        result = get_leaderboard(db_session, subject="InvalidSubject")
        assert result == []

    def test_subject_filter_eligibility_uses_overall_average(self, db_session):
        """Eligibility check uses overall average, not per-subject average."""
        bio_set_id = _create_exam_and_set(db_session, Subject.Biology.value)
        phys_set_id = _create_exam_and_set(db_session, Subject.Physics.value)

        # Alice: high in Biology (80%), low in Physics (20%)
        # Overall average = 50%, eligible
        alice_id = _create_user(db_session, "Alice", "KCET0001")
        _create_submission(db_session, alice_id, bio_set_id, 80.0)
        _create_submission(db_session, alice_id, phys_set_id, 20.0)
        db_session.commit()

        # Filter by Biology: Alice is eligible (overall avg 50% >= 30%)
        result = get_leaderboard(db_session, subject=Subject.Biology.value)
        assert len(result) == 1
        assert result[0].display_name == "Alice"

    def test_subject_filter_with_multiple_submissions_per_student(self, db_session):
        """Multiple submissions in the same subject are all counted."""
        bio_set_id = _create_exam_and_set(db_session, Subject.Biology.value)

        alice_id = _create_user(db_session, "Alice", "KCET0001")
        _create_submission(db_session, alice_id, bio_set_id, 70.0)
        _create_submission(db_session, alice_id, bio_set_id, 80.0)
        _create_submission(db_session, alice_id, bio_set_id, 90.0)

        bob_id = _create_user(db_session, "Bob", "KCET0002")
        _create_submission(db_session, bob_id, bio_set_id, 60.0)
        db_session.commit()

        result = get_leaderboard(db_session, subject=Subject.Biology.value)
        assert len(result) == 2
        # Alice has higher average (80) vs Bob (60)
        assert result[0].display_name == "Alice"
        assert result[0].attempt_count == 3
        assert result[1].display_name == "Bob"
        assert result[1].attempt_count == 1
