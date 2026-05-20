"""SQLAlchemy ORM models for the SmartKCET relational schema.

The schema mirrors the ER diagram in ``design.md`` §Data Models.  Every
table uses UUID primary keys (portable to PostgreSQL via
:class:`sqlalchemy.Uuid`) and TIMESTAMP columns with a server-side default
of ``CURRENT_TIMESTAMP``.

Subject and other constrained string columns use ``CHECK`` constraints —
explicit per the task spec — instead of native ``ENUM`` types so the same
migrations work on both SQLite (development) and PostgreSQL (production).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


# ---------------------------------------------------------------------------
# Subject enum (REQ-8.1)
# ---------------------------------------------------------------------------


class Subject(str, enum.Enum):
    """Allowed values for ``QUESTIONS.subject`` and ``EXAMS.subject``.

    Inheriting from :class:`str` lets the enum members serialise
    transparently when SQLAlchemy stores them as TEXT columns, and lets
    callers compare ``row.subject == Subject.Biology`` without coercion.
    """

    Biology = "Biology"
    Physics = "Physics"
    Chemistry = "Chemistry"
    Mathematics = "Mathematics"


_SUBJECT_VALUES = ", ".join(f"'{s.value}'" for s in Subject)
_SUBJECT_CHECK_SQL = f"subject IN ({_SUBJECT_VALUES})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid_pk() -> Mapped[uuid.UUID]:
    """Standard UUID primary-key column (Python-side default)."""

    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------


class User(Base):
    """Application user — either a registered student or the singleton admin."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("kcet_student_id", name="uq_users_kcet_student_id"),
        CheckConstraint("role IN ('student', 'admin')", name="ck_users_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    # Admins do not have a KCET student id; students always do.
    kcet_student_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lockout_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    leaderboard_score: Mapped[Optional["LeaderboardScore"]] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# QUESTIONS
# ---------------------------------------------------------------------------


class Question(Base):
    """A single MCQ produced by the RAG pipeline."""

    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(_SUBJECT_CHECK_SQL, name="ck_questions_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(32), nullable=False)
    question_text: Mapped[str] = mapped_column(String, nullable=False)
    # List of 4 strings.
    options: Mapped[Any] = mapped_column(JSON, nullable=False)
    # Stored as TEXT per design.md (e.g. "0", "1", "2", "3").
    correct_option: Mapped[str] = mapped_column(String(8), nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    generation_batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    exam_set_links: Mapped[list["ExamSetQuestion"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# EXAMS
# ---------------------------------------------------------------------------


class Exam(Base):
    """A subject-scoped exam composed of exactly four sets (A/B/C/D)."""

    __tablename__ = "exams"
    __table_args__ = (
        CheckConstraint(_SUBJECT_CHECK_SQL, name="ck_exams_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(32), nullable=False)
    exam_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    sets: Mapped[list["ExamSet"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# EXAM_SETS
# ---------------------------------------------------------------------------


class ExamSet(Base):
    """One of the four sets (A, B, C, D) belonging to a parent :class:`Exam`."""

    __tablename__ = "exam_sets"
    __table_args__ = (
        UniqueConstraint("exam_id", "set_label", name="uq_exam_sets_exam_label"),
        CheckConstraint(
            "set_label IN ('A', 'B', 'C', 'D')", name="ck_exam_sets_label"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    exam_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    set_label: Mapped[str] = mapped_column(String(1), nullable=False)

    exam: Mapped["Exam"] = relationship(back_populates="sets")
    question_links: Mapped[list["ExamSetQuestion"]] = relationship(
        back_populates="exam_set", cascade="all, delete-orphan"
    )
    submissions: Mapped[list["Submission"]] = relationship(back_populates="exam_set")


# ---------------------------------------------------------------------------
# EXAM_SET_QUESTIONS (link table)
# ---------------------------------------------------------------------------


class ExamSetQuestion(Base):
    """Association row linking a :class:`Question` to an :class:`ExamSet`."""

    __tablename__ = "exam_set_questions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "exam_set_id", "question_id", name="pk_exam_set_questions"
        ),
    )

    exam_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("exam_sets.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    exam_set: Mapped["ExamSet"] = relationship(back_populates="question_links")
    question: Mapped["Question"] = relationship(back_populates="exam_set_links")


# ---------------------------------------------------------------------------
# SUBMISSIONS
# ---------------------------------------------------------------------------


class Submission(Base):
    """A student's attempt at a particular :class:`ExamSet`."""

    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'failed')", name="ck_submissions_status"
        ),
        # REQ-9.3 idempotency.  A unique index on (user_id, idempotency_key)
        # prevents duplicate rows on retried POSTs while leaving rows with
        # a NULL key (legacy or manual inserts) free of constraint
        # interaction.  SQLite and PostgreSQL both treat NULL values as
        # distinct in a UNIQUE constraint, so legacy rows do not collide.
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_submissions_user_idempotency_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exam_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("exam_sets.id", ondelete="CASCADE"), nullable=False
    )
    answers: Mapped[Any] = mapped_column(JSON, nullable=False)
    score_pct: Mapped[float] = mapped_column(Float, nullable=False)
    topic_breakdown: Mapped[Any] = mapped_column(JSON, nullable=False)
    time_taken_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # REQ-9.3 — client-supplied retry idempotency token.  Nullable so
    # legacy rows stay valid; new rows from /api/student/submit always
    # carry one.  Length cap mirrors the migration column definition.
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="submissions")
    exam_set: Mapped["ExamSet"] = relationship(back_populates="submissions")


# ---------------------------------------------------------------------------
# LEADERBOARD_SCORES
# ---------------------------------------------------------------------------


class LeaderboardScore(Base):
    """Materialised leaderboard row, one per student (REQ-11)."""

    __tablename__ = "leaderboard_scores"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    composite_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    average_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    std_dev: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    # REQ-11.2: average_score >= 30 AND attempt_count >= 1.
    is_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    recomputed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="leaderboard_score")


# ---------------------------------------------------------------------------
# REVOKED_TOKENS (REQ-2.7 / Property 6)
# ---------------------------------------------------------------------------


class RevokedToken(Base):
    """JWT IDs (`jti`) that have been logged out and must be rejected.

    ``expires_at`` mirrors the JWT's original ``exp`` claim so a periodic
    cleanup job can prune entries that no longer matter.
    """

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# INDEXED_FILES (per-subject file tracking for admin uploads)
# ---------------------------------------------------------------------------


class IndexedFile(Base):
    """Tracks files that have been uploaded and indexed into the RAG store."""

    __tablename__ = "indexed_files"
    __table_args__ = (
        UniqueConstraint("subject", "file_hash", name="uq_subject_file_hash"),
        CheckConstraint(_SUBJECT_CHECK_SQL, name="ck_indexed_files_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hex
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


__all__ = [
    "Subject",
    "User",
    "Question",
    "Exam",
    "ExamSet",
    "ExamSetQuestion",
    "Submission",
    "LeaderboardScore",
    "RevokedToken",
    "IndexedFile",
]
