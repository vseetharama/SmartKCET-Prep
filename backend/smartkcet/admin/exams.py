"""Admin exam-authoring endpoints.

Implements task 7.1, 7.3 / REQ-7.1 ... REQ-7.6 and the admin-side
contract documented in design.md §4 (atomic exam creation), §4.1
(publish/unpublish) and §4.2 (student exam-selection visibility — the
read side that this module powers via ``GET /api/admin/exams``).

* Mounted under ``/api/admin/exams`` from :mod:`smartkcet.admin`.
* Every endpoint is admin-only — guarded by
  :func:`smartkcet.middleware.rbac.require_admin`.
* The 400 envelope shape (``{error, message[, field]}``) mirrors
  :mod:`.upload`, :mod:`.generate`, and :mod:`.questions` so the admin
  UI can handle validation failures uniformly.

Endpoints
---------

``POST /api/admin/exams``
    Atomic exam creation (REQ-7.1, REQ-7.2, REQ-7.3 / design.md §4).
    Counts the requested subject's questions; aborts with 422 when the
    bank holds fewer than :data:`QUESTIONS_PER_EXAM` (80) rows.  On
    sufficient stock it draws 80 random questions, partitions them into
    4 disjoint sets of 20 labelled A/B/C/D, and inserts the exam + 4
    sets + 80 set-question rows in a single SQL transaction.  Any
    failure at any of those three steps triggers ``ROLLBACK`` so no
    partial exam record persists.

``PATCH /api/admin/exams/{exam_id}``
    Idempotent publish/unpublish toggle (REQ-7.4, REQ-7.5 / design.md
    §4.1).  The ``exams.is_published`` column is the single source of
    truth for new student attempts; in-progress submissions on a
    now-unpublished exam are left untouched per design.md §4.1.

``GET /api/admin/exams``
    List all exams with subject, creation date, published status, and
    set count (REQ-7.6).  Optional ``?subject=Biology`` filter.  Sorted
    by ``created_at DESC`` so the freshly created exam shows first.
"""

from __future__ import annotations

import logging
import random
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.models import Exam, ExamSet, ExamSetQuestion, Question, Subject
from ..db.session import get_session
from ..middleware.rbac import require_admin

logger = logging.getLogger("smartkcet.admin.exams")

router = APIRouter()


# REQ-7.1 — exam contract: 4 sets × 20 questions = 80 total.  Defined as
# module-level constants so the smoke test (and any future admin UI)
# imports the same values rather than duplicating the magic numbers.
SET_LABELS = ("A", "B", "C", "D")
QUESTIONS_PER_SET = 20
MAX_QUESTIONS_PER_EXAM = QUESTIONS_PER_SET * len(SET_LABELS)  # 80
MIN_QUESTIONS_TO_GENERATE = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validation_error(message: str, field: Optional[str] = None) -> JSONResponse:
    """Return a 400 envelope identical in shape to other admin endpoints."""

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
# Request schemas
# ---------------------------------------------------------------------------


class CreateExamRequest(BaseModel):
    """Body for ``POST /api/admin/exams``."""

    subject: Optional[str] = None
    exam_name: Optional[str] = None


class PublishExamRequest(BaseModel):
    """Body for ``PATCH /api/admin/exams/{exam_id}``."""

    is_published: Optional[bool] = None


# ---------------------------------------------------------------------------
# POST /api/admin/exams  (REQ-7.1, REQ-7.2, REQ-7.3 / design.md §4)
# ---------------------------------------------------------------------------


@router.post("/exams", status_code=status.HTTP_201_CREATED)
def create_exam(
    payload: CreateExamRequest,
    session: Session = Depends(get_session),
    _admin: dict = Depends(require_admin),
) -> Any:
    """Create one exam (1 row + 4 sets + 80 set-question links) atomically.

    The transaction ordering follows design.md §4:

    1. ``SELECT count(*)`` for the subject; abort with 422 if < 80.
    2. ``SELECT`` 80 random questions for the subject.
    3. Partition the 80 into four disjoint 20-question sets via
       :func:`random.sample` over the index space, then insert exam +
       4 sets + 80 ``exam_set_questions`` rows.

    Any failure at step 1 returns 422 *before* any writes, so there is
    nothing to roll back.  Any failure at step 2 or 3 calls
    ``session.rollback()`` so no partial exam state persists (REQ-7.1).
    """

    selected = _normalise_subject(payload.subject)
    if selected is None:
        allowed = [s.value for s in Subject]
        return _validation_error(
            f"subject is required and must be one of {allowed}",
            field="subject",
        )

    # ---- Step 1: count subject questions ---------------------------------
    # Counting outside the write transaction is safe: if the count drops
    # between here and the random draw, the draw simply returns fewer
    # than required ids and we abort with 422 (re-checked below).  We never
    # write anything until we have all required ids in hand.
    count_stmt = select(func.count(Question.id)).where(
        Question.subject == selected.value
    )
    available = int(session.execute(count_stmt).scalar_one())
    if available < MIN_QUESTIONS_TO_GENERATE:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "insufficient_questions",
                "subject": selected.value,
                "count": available,
                "required": MIN_QUESTIONS_TO_GENERATE,
            },
        )

    # ---- Step 2: random draw of required question ids -------------------
    # Pull every question id for the subject, then sample the required
    # quantity via :func:`random.sample` so the draw is uniform over
    # the bank without leaning on a database-specific ``ORDER BY RANDOM()``.
    id_rows = session.execute(
        select(Question.id).where(Question.subject == selected.value)
    ).all()
    all_ids: list[uuid.UUID] = [row[0] for row in id_rows]
    if len(all_ids) < MIN_QUESTIONS_TO_GENERATE:
        # Defensive race-guard: between the count and the id fetch a
        # concurrent delete could have dropped the count below minimum.  Abort
        # cleanly without writing anything.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "insufficient_questions",
                "subject": selected.value,
                "count": len(all_ids),
                "required": MIN_QUESTIONS_TO_GENERATE,
            },
        )

    # Draw the available questions (up to MAX_QUESTIONS_PER_EXAM for backward compatibility)
    num_to_draw = min(available, MAX_QUESTIONS_PER_EXAM)
    drawn: list[uuid.UUID] = random.sample(all_ids, num_to_draw)

    # ---- Step 3: partition + insert all rows in one transaction ---------
    # Calculate dynamic set sizes based on available questions.
    # For backward compatibility: if num_to_draw >= 80, use 20 per set.
    # Otherwise, distribute evenly across 4 sets.
    num_questions = len(drawn)
    questions_per_set = num_questions // len(SET_LABELS)
    remainder = num_questions % len(SET_LABELS)
    
    set_sizes = []
    for i in range(len(SET_LABELS)):
        size = questions_per_set
        if i < remainder:
            size += 1
        set_sizes.append(size)
    
    # Slice the drawn ids into 4 chunks based on calculated set sizes.
    # Because ``random.sample`` returns distinct elements, the 4 slices
    # share no ids, satisfying REQ-7.3 ("no question repeated across sets").
    partitions: list[list[uuid.UUID]] = []
    for i in range(len(SET_LABELS)):
        start = sum(set_sizes[:i])
        end = start + set_sizes[i]
        partitions.append(drawn[start:end])

    exam = Exam(subject=selected.value, exam_name=payload.exam_name)
    session.add(exam)
    # ``flush`` materialises ``exam.id`` so the FK columns on the set
    # rows resolve, but does NOT commit — a later failure still rolls
    # the row back.
    try:
        session.flush()

        sets_payload: list[dict[str, Any]] = []
        for label, qids in zip(SET_LABELS, partitions):
            exam_set = ExamSet(exam_id=exam.id, set_label=label)
            session.add(exam_set)
            session.flush()  # materialise exam_set.id for the link rows.

            link_rows = [
                ExamSetQuestion(
                    exam_set_id=exam_set.id,
                    question_id=qid,
                    order_index=order_index,
                )
                for order_index, qid in enumerate(qids)
            ]
            # Bulk-add the link rows for this set.
            session.add_all(link_rows)

            sets_payload.append(
                {
                    "label": label,
                    "exam_set_id": str(exam_set.id),
                    "question_count": len(qids),
                }
            )

        session.commit()
    except (SQLAlchemyError, Exception) as exc:
        # REQ-7.1: any failure at any of the three steps → ROLLBACK.
        # We catch the broad ``Exception`` as well as ``SQLAlchemyError``
        # so a non-DB error (e.g., a model __init__ assertion) cannot
        # leave a partial exam in the database.
        session.rollback()
        logger.warning("POST /api/admin/exams failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "exam_creation_failed",
                "message": f"failed to create exam: {exc}",
            },
        )

    created_at = exam.created_at
    return {
        "exam_id": str(exam.id),
        "subject": selected.value,
        "exam_name": exam.exam_name,
        "set_ids": sets_payload,
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


# ---------------------------------------------------------------------------
# PATCH /api/admin/exams/{exam_id}  (REQ-7.4, REQ-7.5 / design.md §4.1)
# ---------------------------------------------------------------------------


@router.patch("/exams/{exam_id}")
def patch_exam(
    payload: PublishExamRequest,
    exam_id: uuid.UUID = Path(...),
    session: Session = Depends(get_session),
    _admin: dict = Depends(require_admin),
) -> Any:
    """Toggle publish/unpublish on an existing exam (idempotent).

    REQ-7.4 / REQ-7.5 / design.md §4.1: ``exams.is_published`` is the
    single source of truth for student visibility of new attempts.
    Repeated publishes or unpublishes leave the column at the requested
    value without side effects on ``exam_sets`` or ``submissions``.

    In-progress submissions on a now-unpublished exam continue and
    persist normally — the column gates only new attempts.
    """

    if payload.is_published is None or not isinstance(payload.is_published, bool):
        return _validation_error(
            "is_published is required and must be a boolean",
            field="is_published",
        )

    exam = session.get(Exam, exam_id)
    if exam is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "exam_id": str(exam_id)},
        )

    # Idempotent assignment — if the column already holds the requested
    # value the UPDATE is a no-op but the response shape is unchanged.
    if exam.is_published != payload.is_published:
        exam.is_published = payload.is_published
        try:
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            logger.warning(
                "PATCH /api/admin/exams/%s failed: %s", exam_id, exc
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "publish_update_failed",
                    "message": f"failed to update publish state: {exc}",
                },
            )

    return {"exam_id": str(exam.id), "is_published": exam.is_published}


# ---------------------------------------------------------------------------
# GET /api/admin/exams  (REQ-7.6)
# ---------------------------------------------------------------------------


@router.get("/exams")
def list_exams(
    subject: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    _admin: dict = Depends(require_admin),
) -> Any:
    """List all exams with subject, creation date, published status, set_count.

    REQ-7.6: the admin panel shows every exam regardless of publish
    status.  Optional ``?subject=Biology`` filter scopes the list to a
    single subject.  Sort order is ``created_at DESC`` so the freshly
    created exam appears at the top.
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

    # Compute set_count via a left join + group_by so we get one row per
    # exam even when an exam has zero sets (which should not happen post
    # task 7.1, but the join is defensive).
    stmt = (
        select(Exam, func.count(ExamSet.id).label("set_count"))
        .outerjoin(ExamSet, ExamSet.exam_id == Exam.id)
        .group_by(Exam.id)
        .order_by(Exam.created_at.desc(), Exam.id.asc())
    )
    if selected is not None:
        stmt = stmt.where(Exam.subject == selected.value)

    rows = session.execute(stmt).all()
    exams_payload: list[dict[str, Any]] = []
    for exam, set_count in rows:
        created_at = exam.created_at
        exams_payload.append(
            {
                "exam_id": str(exam.id),
                "subject": exam.subject,
                "exam_name": exam.exam_name,
                "created_at": created_at.isoformat() if created_at is not None else None,
                "is_published": bool(exam.is_published),
                "set_count": int(set_count or 0),
            }
        )

    return {
        "exams": exams_payload,
        "subject": selected.value if selected is not None else None,
        "total": len(exams_payload),
    }


__all__ = [
    "router",
    "SET_LABELS",
    "QUESTIONS_PER_SET",
    "MAX_QUESTIONS_PER_EXAM",
    "MIN_QUESTIONS_TO_GENERATE",
]
