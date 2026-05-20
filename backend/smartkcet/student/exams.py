"""Student exam-selection endpoint.

Implements task 7.5 / REQ-8.1, REQ-8.2, REQ-8.3 and the read side of the
contract documented in design.md §4.2 ("Student Exam-Selection
Visibility").

* Mounted under ``/api/student/exams`` from :mod:`smartkcet.student`.
* Student-only — guarded by
  :func:`smartkcet.middleware.rbac.require_student`.
* Subjects with **no published exam** are omitted from the response per
  REQ-8.2 / design.md §4.2.  When no subject has any published exam the
  response shape collapses to ``{"subjects": []}`` and the UI renders
  the "no exams currently available" empty state.
* Optional ``?subject=Biology`` query parameter scopes the response to
  one subject; mismatched subjects yield ``{"subjects": []}`` rather
  than a 400 (the spec lists no validation error for this case — the
  filter is purely additive).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Exam, ExamSet, ExamSetQuestion, Question, Subject
from ..db.session import get_session
from ..middleware.rbac import require_student

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validation_error(message: str, field: Optional[str] = None) -> JSONResponse:
    """Return a 400 envelope identical in shape to the admin endpoints."""

    body: dict[str, Any] = {"error": "validation_error", "message": message}
    if field is not None:
        body["field"] = field
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=body)


def _normalise_subject(value: Optional[str]) -> Optional[Subject]:
    """Return the matching :class:`Subject` enum or ``None`` for invalid input."""

    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return Subject(stripped)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# GET /api/student/exams  (REQ-8.1, REQ-8.2, REQ-8.3 / design.md §4.2)
# ---------------------------------------------------------------------------


@router.get("/exams")
def list_published_exams(
    subject: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    _student: dict = Depends(require_student),
) -> Any:
    """Return per-subject groupings of published exams visible to students.

    Response shape::

        {
          "subjects": [
            {
              "subject": "Biology",
              "available_exams": 2,
              "exams": [
                {"exam_id": "...", "created_at": "...", "set_count": 4},
                ...
              ]
            },
            ...
          ]
        }

    Subjects without at least one published exam are omitted.  When the
    optional ``?subject=`` filter narrows the scope to a single subject
    that has no published exam, the response is ``{"subjects": []}``.
    """

    selected: Optional[Subject] = None
    if subject is not None:
        normalised = _normalise_subject(subject)
        if normalised is None:
            allowed = [s.value for s in Subject]
            return _validation_error(
                f"subject must be one of {allowed}",
                field="subject",
            )
        selected = normalised

    # Pull every PUBLISHED exam (optionally scoped) plus its set_count
    # in a single query.  Sorting by ``created_at DESC`` matches the
    # admin list order so the most recent exam shows first when an
    # admin publishes a fresh batch.
    stmt = (
        select(Exam, func.count(ExamSet.id).label("set_count"))
        .outerjoin(ExamSet, ExamSet.exam_id == Exam.id)
        .where(Exam.is_published.is_(True))
        .group_by(Exam.id)
        .order_by(Exam.created_at.desc(), Exam.id.asc())
    )
    if selected is not None:
        stmt = stmt.where(Exam.subject == selected.value)

    rows = session.execute(stmt).all()

    # Group rows by subject.  ``buckets`` preserves insertion order so a
    # subject's first-seen ``created_at`` decides where it appears in
    # the response — combined with the SQL ``ORDER BY created_at DESC``
    # this mirrors the admin-list ordering.
    buckets: dict[str, list[dict[str, Any]]] = {}
    for exam, set_count in rows:
        created_at = exam.created_at
        bucket = buckets.setdefault(exam.subject, [])
        bucket.append(
            {
                "exam_id": str(exam.id),
                "created_at": (
                    created_at.isoformat() if created_at is not None else None
                ),
                "set_count": int(set_count or 0),
            }
        )

    subjects_payload: list[dict[str, Any]] = [
        {
            "subject": subject_value,
            "available_exams": len(exams),
            "exams": exams,
        }
        for subject_value, exams in buckets.items()
    ]

    return {"subjects": subjects_payload}


# ---------------------------------------------------------------------------
# GET /api/student/exams/{exam_set_id}  (REQ-9.1 / task 14.3)
# ---------------------------------------------------------------------------


@router.get("/exams/{exam_set_id}")
def get_exam_set_questions(
    exam_set_id: str,
    session: Session = Depends(get_session),
    _student: dict = Depends(require_student),
) -> Any:
    """Return the questions for a specific exam set so the student can take the exam.

    Response shape::

        {
          "exam_set_id": "uuid",
          "set_label": "A",
          "subject": "Biology",
          "difficulty": "medium",
          "questions": [
            {"q": "...", "type": "MCQ", "opts": [...], "topic": "...", "marks": 1},
            ...
          ]
        }

    Questions are ordered by ``ExamSetQuestion.order_index`` so the
    student's answer map keys (``"0"`` ... ``"19"``) align with positions.
    """
    import uuid as _uuid

    try:
        set_id = _uuid.UUID(exam_set_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "validation_error", "message": "exam_set_id must be a valid UUID"},
        )

    exam_set = session.get(ExamSet, set_id)
    if exam_set is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "resource": "exam_set", "value": str(set_id)},
        )

    # Verify the parent exam is published
    exam = session.get(Exam, exam_set.exam_id)
    if exam is None or not exam.is_published:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "message": "Exam is not available"},
        )

    # Load questions ordered by position
    stmt = (
        select(Question, ExamSetQuestion.order_index)
        .join(ExamSetQuestion, ExamSetQuestion.question_id == Question.id)
        .where(ExamSetQuestion.exam_set_id == set_id)
        .order_by(ExamSetQuestion.order_index.asc())
    )
    rows = session.execute(stmt).all()

    questions = []
    for question, _order in rows:
        questions.append({
            "q": question.question_text,
            "type": "MCQ",
            "opts": question.options,
            "topic": question.topic or "General",
            "ans": question.correct_option,
            "marks": 1,
        })

    return {
        "exam_set_id": str(set_id),
        "set_label": exam_set.set_label,
        "subject": exam.subject,
        "difficulty": "medium",
        "questions": questions,
    }


__all__ = ["router"]
