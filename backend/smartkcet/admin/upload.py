"""Admin file-upload endpoint with per-subject FAISS indexing.

Implements task 4.3 / REQ-5.1, REQ-5.3, REQ-5.4, REQ-8.5:

* Mounted under ``/api/admin/upload`` from :mod:`smartkcet.admin`.
* Admin-only — guarded by :func:`smartkcet.middleware.rbac.require_admin`.
* Required ``subject`` form field (``Biology|Physics|Chemistry|Mathematics``);
  missing or unrecognised values short-circuit with HTTP 400 before any
  file is parsed.
* Up to 10 files per batch (REQ-5.3); larger batches are rejected with
  HTTP 400.
* Per-file extraction errors / unsupported extensions / empty OCR
  results are aggregated into the response ``warnings`` list **without**
  aborting the batch (REQ-5.4).
* Indexing is scoped strictly to the requested subject's FAISS store via
  :data:`smartkcet.rag.store.stores`; other subjects are never touched
  (REQ-5.1, REQ-8.5).
* Duplicate detection via SHA-256 file hash per subject.
* Individual file upload endpoint for per-file progress tracking.
* List indexed files endpoint for frontend display.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import IndexedFile, Question, Subject
from ..db.session import get_session
from ..middleware.rbac import require_admin
from ..rag.mcq_extractor import extract_or_generate_mcqs

# Graceful degradation for Python 3.14 compatibility
# pytesseract is not available in Python 3.14 (pkgutil.find_loader removed)
try:
    from ..rag.parsing import (
        chunk_text,
        extract_text_from_docx,
        extract_text_from_pdf,
        extract_text_from_txt,
    )
    PARSING_AVAILABLE = True
except ImportError as e:
    logger = logging.getLogger("smartkcet.admin.upload")
    logger.warning(
        "RAG parsing module not available (Python 3.14 compatibility): %s. "
        "File upload functionality will be limited.",
        e,
    )
    PARSING_AVAILABLE = False
    # Provide stub functions so the module can still be imported
    chunk_text = None
    extract_text_from_docx = None
    extract_text_from_pdf = None
    extract_text_from_txt = None

from ..rag.store import stores

logger = logging.getLogger("smartkcet.admin.upload")

router = APIRouter()


# REQ-5.3 — matches the legacy ``/upload`` cap so admins don't experience
# a regression when migrating to the role-scoped endpoint.
MAX_FILES_PER_BATCH = 10


def _validation_error(message: str, field: Optional[str] = None) -> JSONResponse:
    """Return a 400 JSON envelope identical in shape to other auth/admin errors."""

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


def _extract_text(filename: str, content: bytes) -> Optional[str]:
    """Dispatch on the filename extension; return ``None`` for unsupported types."""

    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        logger.info("Extracting text from PDF: %s (%d bytes)", filename, len(content))
        return extract_text_from_pdf(content)
    if lowered.endswith(".docx"):
        logger.info("Extracting text from DOCX: %s (%d bytes)", filename, len(content))
        return extract_text_from_docx(content)
    if lowered.endswith(".txt"):
        logger.info("Extracting text from TXT: %s (%d bytes)", filename, len(content))
        return extract_text_from_txt(content)
    logger.warning("Unsupported file extension: %s", filename)
    return None


def _compute_file_hash(content: bytes) -> str:
    """Compute SHA-256 hex digest of file content."""
    return hashlib.sha256(content).hexdigest()


def _check_duplicate(db: Session, subject: str, file_hash: str) -> Optional[IndexedFile]:
    """Check if a file with the same hash already exists for admin (institution_id IS NULL)."""
    stmt = select(IndexedFile).where(
        IndexedFile.subject == subject,
        IndexedFile.file_hash == file_hash,
        IndexedFile.institution_id.is_(None),
    )
    return db.execute(stmt).scalar_one_or_none()


def _record_indexed_file(
    db: Session,
    subject: str,
    filename: str,
    file_hash: str,
    file_size: int,
    chunk_count: int,
) -> IndexedFile:
    """Insert a new admin IndexedFile record (institution_id=NULL) and commit."""
    record = IndexedFile(
        subject=subject,
        filename=filename,
        file_hash=file_hash,
        file_size=file_size,
        chunk_count=chunk_count,
        institution_id=None,  # admin/global
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _store_mcqs_in_db(
    db: Session,
    mcqs: List[dict],
    subject: str,
    batch_id: uuid.UUID,
) -> tuple[int, int, Optional[str]]:
    """Store extracted MCQs as platform-wide Question rows (institution_id=NULL).

    Returns a tuple of (stored, skipped, error):
    - stored: number of questions successfully stored and committed
    - skipped: number of questions skipped due to validation errors
    - error: None on success, or error message string if commit failed
    """
    stored = 0
    skipped = 0
    for mcq in mcqs:
        q_text = mcq.get("q", "").strip()
        opts = mcq.get("opts", [])
        ans = mcq.get("ans", 0)
        topic = mcq.get("topic", "General")

        # Validate
        if not q_text or not isinstance(opts, list) or len(opts) != 4:
            logger.debug("Skipping invalid MCQ: q_text=%s, opts_len=%d", len(q_text), len(opts))
            skipped += 1
            continue

        try:
            row = Question(
                subject=subject,
                question_text=q_text,
                options=opts,
                correct_option=str(ans),
                topic=topic if isinstance(topic, str) else "General",
                generation_batch_id=batch_id,
                institution_id=None,  # platform-wide
            )
            db.add(row)
            stored += 1
        except Exception as e:
            logger.error("Failed to create Question row: %s", e)
            skipped += 1
            continue

    if stored > 0:
        try:
            logger.info("Committing %d questions to database", stored)
            db.commit()
            logger.info("Successfully committed %d questions", stored)
            return stored, skipped, None
        except Exception as exc:
            logger.error("Failed to commit MCQs to DB: %s", exc, exc_info=True)
            db.rollback()
            error_msg = f"Database commit failed: {type(exc).__name__}: {str(exc)}"
            return 0, skipped, error_msg

    return stored, skipped, None


# ─── GET /upload/files — list indexed files for a subject ─────────────────────


@router.get("/upload/files")
async def list_indexed_files(
    subject: str = Query(..., description="Subject to list files for"),
    _admin: dict = Depends(require_admin),
    db: Session = Depends(get_session),
) -> Any:
    """Return all previously indexed files for a subject."""

    selected = _normalise_subject(subject)
    if selected is None:
        allowed = [s.value for s in Subject]
        return _validation_error(
            f"subject is required and must be one of {allowed}",
            field="subject",
        )

    stmt = (
        select(IndexedFile)
        .where(
            IndexedFile.subject == selected.value,
            IndexedFile.institution_id.is_(None),  # Only admin-owned files
        )
        .order_by(IndexedFile.indexed_at.desc())
    )
    files = db.execute(stmt).scalars().all()

    return {
        "subject": selected.value,
        "files": [
            {
                "id": str(f.id),
                "filename": f.filename,
                "file_hash": f.file_hash,
                "file_size": f.file_size,
                "chunk_count": f.chunk_count,
                "indexed_at": f.indexed_at.isoformat() if f.indexed_at else None,
            }
            for f in files
        ],
    }


# ─── POST /upload/single — individual file upload with progress ───────────────


@router.post("/upload/single")
async def upload_single(
    subject: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
    _admin: dict = Depends(require_admin),
    db: Session = Depends(get_session),
) -> Any:
    """Index a single uploaded file. Returns per-file status for progress tracking."""

    selected = _normalise_subject(subject)
    if selected is None:
        allowed = [s.value for s in Subject]
        return _validation_error(
            f"subject is required and must be one of {allowed}",
            field="subject",
        )

    filename = file.filename or ""
    content = await file.read()
    file_size = len(content)
    file_hash = _compute_file_hash(content)

    # Check for duplicate
    existing = _check_duplicate(db, selected.value, file_hash)
    if existing is not None:
        return {
            "status": "duplicate",
            "filename": filename,
            "file_hash": file_hash,
            "file_size": file_size,
            "chunk_count": existing.chunk_count,
            "message": f"File already indexed as '{existing.filename}' with {existing.chunk_count} chunks",
        }

    # Extract text
    text = _extract_text(filename, content)
    if text is None:
        return {
            "status": "unsupported",
            "filename": filename,
            "file_hash": file_hash,
            "file_size": file_size,
            "chunk_count": 0,
            "message": f"Unsupported file type: {filename}",
        }

    if not text.strip():
        return {
            "status": "empty",
            "filename": filename,
            "file_hash": file_hash,
            "file_size": file_size,
            "chunk_count": 0,
            "message": "No text could be extracted from this file",
        }

    # Chunk text
    chunks = chunk_text(text)
    if not chunks:
        return {
            "status": "empty",
            "filename": filename,
            "file_hash": file_hash,
            "file_size": file_size,
            "chunk_count": 0,
            "message": "Text too short to produce meaningful chunks",
        }

    # Index into FAISS
    stores.add(selected, chunks)

    # Record in database
    _record_indexed_file(
        db,
        subject=selected.value,
        filename=filename,
        file_hash=file_hash,
        file_size=file_size,
        chunk_count=len(chunks),
    )

    # Extract MCQs from the full text and store in DB
    mcq_batch_id = uuid.uuid4()
    try:
        mcqs = extract_or_generate_mcqs(text, topic=selected.value, min_questions=5)
        logger.info(
            "File '%s': extract_or_generate_mcqs returned %d MCQs",
            filename,
            len(mcqs) if mcqs else 0,
        )
        if not mcqs:
            logger.warning("File '%s': No MCQs extracted or generated for %s", filename, selected.value)
    except Exception as e:
        logger.error("File '%s': MCQ extraction failed: %s", filename, e, exc_info=True)
        mcqs = []
    
    questions_extracted, questions_skipped, storage_error = _store_mcqs_in_db(db, mcqs, selected.value, mcq_batch_id)
    logger.info(
        "File '%s': extracted %d MCQs into question bank for %s (skipped: %d)",
        filename,
        questions_extracted,
        selected.value,
        questions_skipped,
    )
    
    if storage_error:
        logger.error("File '%s': Storage error: %s", filename, storage_error)
        return {
            "status": "storage_error",
            "filename": filename,
            "file_hash": file_hash,
            "file_size": file_size,
            "chunk_count": len(chunks),
            "questions_extracted": questions_extracted,
            "error": storage_error,
            "message": f"File indexed with {len(chunks)} chunks but MCQ storage failed: {storage_error}",
        }

    return {
        "status": "indexed",
        "filename": filename,
        "file_hash": file_hash,
        "file_size": file_size,
        "chunk_count": len(chunks),
        "questions_extracted": questions_extracted,
        "message": f"Successfully indexed {len(chunks)} chunks, extracted {questions_extracted} questions",
    }


# ─── POST /upload — batch upload (backward compat) ────────────────────────────


@router.post("/upload")
async def upload(
    subject: Optional[str] = Form(default=None),
    files: List[UploadFile] = File(default_factory=list),
    _admin: dict = Depends(require_admin),
    db: Session = Depends(get_session),
) -> Any:
    """Index uploaded files into the requested subject's FAISS store.

    Now includes duplicate detection — files with matching SHA-256 hash
    for the same subject are skipped and returned in ``already_indexed``.
    """

    selected = _normalise_subject(subject)
    if selected is None:
        allowed = [s.value for s in Subject]
        return _validation_error(
            f"subject is required and must be one of {allowed}",
            field="subject",
        )

    if len(files) > MAX_FILES_PER_BATCH:
        return _validation_error(
            f"Maximum {MAX_FILES_PER_BATCH} files per upload batch",
            field="files",
        )

    warnings: List[str] = []
    already_indexed: List[dict[str, Any]] = []
    file_errors: List[dict[str, Any]] = []
    indexed_files = 0
    total_chunks = 0
    total_questions_extracted = 0

    for upload_file in files:
        filename = upload_file.filename or ""
        content = await upload_file.read()
        file_size = len(content)
        file_hash = _compute_file_hash(content)

        logger.info("Processing file: %s (%d bytes, hash: %s)", filename, file_size, file_hash[:12])

        # Duplicate detection
        existing = _check_duplicate(db, selected.value, file_hash)
        if existing is not None:
            logger.info(
                "File '%s' is a duplicate of '%s' (hash: %s) → skipping",
                filename,
                existing.filename,
                file_hash[:12],
            )
            already_indexed.append({
                "filename": filename,
                "existing_filename": existing.filename,
                "file_hash": file_hash,
                "chunk_count": existing.chunk_count,
                "indexed_at": existing.indexed_at.isoformat() if existing.indexed_at else None,
            })
            continue

        text = _extract_text(filename, content)
        if text is None:
            logger.warning(
                "File '%s': unsupported extension or extraction returned None → added to warnings",
                filename,
            )
            warnings.append(filename)
            continue

        if not text.strip():
            logger.warning(
                "File '%s': extraction returned empty text (0 chars after strip) → added to warnings",
                filename,
            )
            warnings.append(filename)
            continue

        chunks = chunk_text(text)
        if not chunks:
            logger.warning(
                "File '%s': text too short to produce chunks (%d chars) → added to warnings",
                filename,
                len(text.strip()),
            )
            warnings.append(filename)
            continue

        # REQ-5.1 / REQ-8.5: mutate only the selected subject's index.
        logger.info(
            "File '%s': successfully extracted %d chars → %d chunks → indexing into %s",
            filename,
            len(text.strip()),
            len(chunks),
            selected.value,
        )
        stores.add(selected, chunks)

        # Record in database
        _record_indexed_file(
            db,
            subject=selected.value,
            filename=filename,
            file_hash=file_hash,
            file_size=file_size,
            chunk_count=len(chunks),
        )

        # Extract MCQs from the full text and store in DB
        mcq_batch_id = uuid.uuid4()
        try:
            mcqs = extract_or_generate_mcqs(text, topic=selected.value, min_questions=5)
            logger.info(
                "File '%s': extract_or_generate_mcqs returned %d MCQs",
                filename,
                len(mcqs) if mcqs else 0,
            )
            if not mcqs:
                logger.warning("File '%s': No MCQs extracted or generated for %s", filename, selected.value)
        except Exception as e:
            logger.error("File '%s': MCQ extraction failed: %s", filename, e, exc_info=True)
            mcqs = []
        
        questions_extracted, questions_skipped, storage_error = _store_mcqs_in_db(db, mcqs, selected.value, mcq_batch_id)
        logger.info(
            "File '%s': extracted %d MCQs into question bank for %s (skipped: %d)",
            filename,
            questions_extracted,
            selected.value,
            questions_skipped,
        )
        
        # Track per-file errors
        if storage_error:
            logger.error("File '%s': Storage error: %s", filename, storage_error)
            file_errors.append({
                "filename": filename,
                "file_hash": file_hash,
                "chunk_count": len(chunks),
                "attempted_questions": len(mcqs),
                "stored_questions": questions_extracted,
                "skipped_questions": questions_skipped,
                "error_reason": storage_error,
            })
            # File was indexed in FAISS but MCQs failed to store — log warning
            warnings.append(f"{filename}: File indexed but MCQ storage failed - {storage_error}")
            continue

        indexed_files += 1
        total_chunks += len(chunks)
        total_questions_extracted += questions_extracted

    return {
        "success": True,
        "subject": selected.value,
        "indexed_files": indexed_files,
        "total_chunks": total_chunks,
        "questions_extracted": total_questions_extracted,
        "warnings": warnings,
        "already_indexed": already_indexed,
        "file_errors": file_errors,
    }


# ─── POST /upload/delete — delete indexed file ───────────────────────────────


@router.post("/upload/delete")
async def delete_indexed_file(
    file_id: str = Body(..., description="UUID of the file to delete", embed=True),
    _admin: dict = Depends(require_admin),
    db: Session = Depends(get_session),
) -> Any:
    """Delete an indexed file (platform admin only).
    
    This endpoint:
    1. Validates file_id is a valid UUID
    2. Retrieves the file from the database
    3. Verifies it exists and belongs to admin (institution_id is NULL)
    4. Deletes the file record from indexed_files table
    5. Returns success response
    
    Errors:
    - 400: Invalid file_id or validation error
    - 401: Unauthorized (handled by require_admin)
    - 403: Forbidden (file belongs to institution)
    - 404: File not found
    - 500: Database error
    """
    
    # Validate file_id is a valid UUID
    try:
        file_uuid = uuid.UUID(file_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "validation_error",
                "message": "file_id must be a valid UUID",
                "field": "file_id",
            },
        )
    
    # Retrieve the file from database
    stmt = select(IndexedFile).where(IndexedFile.id == file_uuid)
    indexed_file = db.execute(stmt).scalar_one_or_none()
    
    if indexed_file is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "not_found",
                "message": "Indexed file not found",
            },
        )
    
    # Verify file belongs to admin (institution_id must be NULL)
    if indexed_file.institution_id is not None:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": "forbidden",
                "message": "This file belongs to an institution and cannot be deleted by platform admin",
            },
        )
    
    try:
        # Delete the file record (soft delete or hard delete)
        # Note: Questions are not directly linked to files via foreign key,
        # so they are not cascade deleted. They remain in the question bank.
        db.delete(indexed_file)
        db.commit()
        
        logger.info(
            "File deleted successfully: id=%s, filename=%s, subject=%s",
            file_uuid,
            indexed_file.filename,
            indexed_file.subject,
        )
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "message": "File deleted successfully",
                "file_id": str(file_uuid),
                "filename": indexed_file.filename,
            },
        )
    
    except Exception as e:
        db.rollback()
        logger.error(
            "Failed to delete indexed file: id=%s, error=%s",
            file_uuid,
            str(e),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "message": "Failed to delete file",
            },
        )


__all__ = ["router", "MAX_FILES_PER_BATCH"]
