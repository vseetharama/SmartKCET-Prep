"""Admin KCET Syllabus management API.

Endpoints
---------
GET    /api/admin/syllabus             – list all topics (with filters)
GET    /api/admin/syllabus/counts      – chapter counts per subject/PUC
POST   /api/admin/syllabus             – add a new topic
PATCH  /api/admin/syllabus/{id}        – edit topic (name, order, active, description)
DELETE /api/admin/syllabus/{id}        – delete a topic

Public (no auth required)
GET    /api/syllabus                   – all active topics (for students/institutions)
GET    /api/syllabus/{subject}         – active topics for one subject
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.models import SyllabusTopic, Subject
from ..db.session import get_async_session as get_session
from ..middleware.rbac import require_admin

logger = logging.getLogger("smartkcet.admin.syllabus")

router = APIRouter()
public_router = APIRouter()   # mounted separately — no auth


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialise(t: SyllabusTopic) -> dict[str, Any]:
    return {
        "id": t.id,
        "subject": t.subject,
        "puc_year": t.puc_year,
        "chapter_number": t.chapter_number,
        "chapter_name": t.chapter_name,
        "display_order": t.display_order,
        "description": t.description,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _validation_error(msg: str, field: Optional[str] = None) -> JSONResponse:
    body: dict[str, Any] = {"error": "validation_error", "message": msg}
    if field:
        body["field"] = field
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=body)


VALID_PUC = {"1st PUC", "2nd PUC"}
VALID_SUBJECTS = {s.value for s in Subject}


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class CreateTopicRequest(BaseModel):
    subject: str
    puc_year: str
    chapter_number: int
    chapter_name: str
    display_order: int = 0
    description: Optional[str] = None
    is_active: bool = True


class PatchTopicRequest(BaseModel):
    chapter_name: Optional[str] = None
    display_order: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# PUBLIC endpoints (no auth)
# ---------------------------------------------------------------------------

@public_router.get("/syllabus")
def list_syllabus_public(
    subject: Optional[str] = Query(default=None),
    puc_year: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
) -> Any:
    """Return all active KCET syllabus topics — accessible by students and institutions."""
    stmt = (
        select(SyllabusTopic)
        .where(SyllabusTopic.is_active.is_(True))
        .order_by(
            SyllabusTopic.subject,
            SyllabusTopic.puc_year,
            SyllabusTopic.display_order,
            SyllabusTopic.chapter_number,
        )
    )
    if subject:
        if subject not in VALID_SUBJECTS:
            return _validation_error(f"subject must be one of {sorted(VALID_SUBJECTS)}")
        stmt = stmt.where(SyllabusTopic.subject == subject)
    if puc_year:
        if puc_year not in VALID_PUC:
            return _validation_error("puc_year must be '1st PUC' or '2nd PUC'")
        stmt = stmt.where(SyllabusTopic.puc_year == puc_year)

    rows = session.execute(stmt).scalars().all()

    # Group into nested structure: subject → puc_year → chapters
    grouped: dict[str, dict[str, list]] = {}
    for t in rows:
        grouped.setdefault(t.subject, {}).setdefault(t.puc_year, []).append(_serialise(t))

    result = []
    for subj, puc_map in grouped.items():
        puc_list = []
        for puc, chapters in sorted(puc_map.items()):
            puc_list.append({
                "puc_year": puc,
                "chapters": chapters,
                "total_chapters": len(chapters),
            })
        result.append({
            "subject": subj,
            "puc_years": puc_list,
            "total_chapters": sum(len(v) for v in puc_map.values()),
        })

    return {
        "subjects": result,
        "total_topics": len(rows),
    }


@public_router.get("/syllabus/{subject}")
def get_syllabus_by_subject(
    subject: str = Path(...),
    session: Session = Depends(get_session),
) -> Any:
    """Return active topics for one subject, grouped by PUC year."""
    if subject not in VALID_SUBJECTS:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Subject '{subject}' not found"},
        )
    stmt = (
        select(SyllabusTopic)
        .where(SyllabusTopic.subject == subject, SyllabusTopic.is_active.is_(True))
        .order_by(SyllabusTopic.puc_year, SyllabusTopic.display_order, SyllabusTopic.chapter_number)
    )
    rows = session.execute(stmt).scalars().all()

    puc_map: dict[str, list] = {}
    for t in rows:
        puc_map.setdefault(t.puc_year, []).append(_serialise(t))

    return {
        "subject": subject,
        "puc_years": [
            {"puc_year": p, "chapters": chs, "total_chapters": len(chs)}
            for p, chs in sorted(puc_map.items())
        ],
        "total_chapters": len(rows),
    }


# ---------------------------------------------------------------------------
# ADMIN endpoints
# ---------------------------------------------------------------------------

@router.get("/syllabus/counts")
def get_topic_counts(
    session: Session = Depends(get_session),
    _admin: dict = Depends(require_admin),
) -> Any:
    """Per-subject, per-PUC chapter counts (all + active)."""
    rows = session.execute(
        select(
            SyllabusTopic.subject,
            SyllabusTopic.puc_year,
            func.count(SyllabusTopic.id).label("total"),
            func.sum(
                func.cast(SyllabusTopic.is_active, type_=type(1))
            ).label("active"),
        )
        .group_by(SyllabusTopic.subject, SyllabusTopic.puc_year)
        .order_by(SyllabusTopic.subject, SyllabusTopic.puc_year)
    ).all()

    counts = [
        {"subject": r.subject, "puc_year": r.puc_year, "total": r.total, "active": r.active or 0}
        for r in rows
    ]
    return {"counts": counts}


@router.get("/syllabus")
def list_topics(
    subject: Optional[str] = Query(default=None),
    puc_year: Optional[str] = Query(default=None),
    include_inactive: bool = Query(default=True),
    session: Session = Depends(get_session),
    _admin: dict = Depends(require_admin),
) -> Any:
    """Admin: list all syllabus topics with optional filters."""
    stmt = select(SyllabusTopic).order_by(
        SyllabusTopic.subject,
        SyllabusTopic.puc_year,
        SyllabusTopic.display_order,
        SyllabusTopic.chapter_number,
    )
    if subject:
        if subject not in VALID_SUBJECTS:
            return _validation_error(f"subject must be one of {sorted(VALID_SUBJECTS)}")
        stmt = stmt.where(SyllabusTopic.subject == subject)
    if puc_year:
        if puc_year not in VALID_PUC:
            return _validation_error("puc_year must be '1st PUC' or '2nd PUC'")
        stmt = stmt.where(SyllabusTopic.puc_year == puc_year)
    if not include_inactive:
        stmt = stmt.where(SyllabusTopic.is_active.is_(True))

    rows = session.execute(stmt).scalars().all()
    return {"topics": [_serialise(t) for t in rows], "total": len(rows)}


@router.post("/syllabus", status_code=status.HTTP_201_CREATED)
def create_topic(
    payload: CreateTopicRequest,
    session: Session = Depends(get_session),
    _admin: dict = Depends(require_admin),
) -> Any:
    """Admin: add a new syllabus chapter."""
    if payload.subject not in VALID_SUBJECTS:
        return _validation_error(f"subject must be one of {sorted(VALID_SUBJECTS)}", "subject")
    if payload.puc_year not in VALID_PUC:
        return _validation_error("puc_year must be '1st PUC' or '2nd PUC'", "puc_year")
    if not payload.chapter_name.strip():
        return _validation_error("chapter_name is required", "chapter_name")
    if payload.chapter_number < 1:
        return _validation_error("chapter_number must be >= 1", "chapter_number")

    topic = SyllabusTopic(
        subject=payload.subject,
        puc_year=payload.puc_year,
        chapter_number=payload.chapter_number,
        chapter_name=payload.chapter_name.strip(),
        display_order=payload.display_order,
        description=payload.description,
        is_active=payload.is_active,
    )
    session.add(topic)
    try:
        session.commit()
        session.refresh(topic)
    except SQLAlchemyError as exc:
        session.rollback()
        if "UNIQUE" in str(exc).upper():
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "error": "duplicate_chapter",
                    "message": f"Chapter {payload.chapter_number} already exists for {payload.subject} {payload.puc_year}",
                },
            )
        logger.warning("POST /admin/syllabus failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "db_error", "message": str(exc)},
        )
    return _serialise(topic)


@router.patch("/syllabus/{topic_id}")
def patch_topic(
    payload: PatchTopicRequest,
    topic_id: int = Path(...),
    session: Session = Depends(get_session),
    _admin: dict = Depends(require_admin),
) -> Any:
    """Admin: edit a syllabus topic (name, order, active status, description)."""
    topic = session.get(SyllabusTopic, topic_id)
    if topic is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "id": topic_id},
        )

    if payload.chapter_name is not None:
        if not payload.chapter_name.strip():
            return _validation_error("chapter_name cannot be empty", "chapter_name")
        topic.chapter_name = payload.chapter_name.strip()
    if payload.display_order is not None:
        topic.display_order = payload.display_order
    if payload.description is not None:
        topic.description = payload.description
    if payload.is_active is not None:
        topic.is_active = payload.is_active

    try:
        session.commit()
        session.refresh(topic)
    except SQLAlchemyError as exc:
        session.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": "db_error", "message": str(exc)},
        )
    return _serialise(topic)


@router.delete("/syllabus/{topic_id}")
def delete_topic(
    topic_id: int = Path(...),
    session: Session = Depends(get_session),
    _admin: dict = Depends(require_admin),
) -> Any:
    """Admin: permanently delete a syllabus topic."""
    topic = session.get(SyllabusTopic, topic_id)
    if topic is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "id": topic_id},
        )
    try:
        session.execute(delete(SyllabusTopic).where(SyllabusTopic.id == topic_id))
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": "db_error", "message": str(exc)},
        )
    return {"deleted": True, "id": topic_id}


__all__ = ["router", "public_router"]
