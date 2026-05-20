"""KCET_Student_ID generator.

REQ-1.1 mandates the format ``KCET\\d{4}`` — the literal prefix ``KCET``
followed by a zero-padded 4-digit sequence number.  This module owns the
allocation logic.

The generator scans the existing ``users.kcet_student_id`` column for the
highest assigned numeric suffix and returns the next one.  It is
race-free in the single-writer (SQLite, dev) deployment; a
``UNIQUE`` constraint on ``users.kcet_student_id`` provides defence in
depth in case of concurrent inserts.

Calling :func:`next_kcet_id` does *not* allocate a row in the DB — it
simply returns the next ID string.  Persisting the new user (and thus
"consuming" the ID) is the caller's responsibility, normally inside the
same transaction as the duplicate-email check + ``hash_password`` flow.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import User

# Public regex — also useful for tests.
KCET_ID_RE = re.compile(r"^KCET\d{4}$")

_PREFIX = "KCET"
_DIGITS = 4


def format_kcet_id(n: int) -> str:
    """Format ``n`` as a zero-padded KCET_Student_ID."""

    if n < 0:
        raise ValueError("kcet sequence number must be non-negative")
    return f"{_PREFIX}{n:0{_DIGITS}d}"


def parse_kcet_id(kcet_id: str) -> int | None:
    """Return the integer suffix of ``kcet_id`` or ``None`` if malformed."""

    if not isinstance(kcet_id, str):
        return None
    if not KCET_ID_RE.match(kcet_id):
        return None
    return int(kcet_id[len(_PREFIX):])


def next_kcet_id(session: Session) -> str:
    """Return the next available KCET_Student_ID.

    The function inspects every non-null ``kcet_student_id`` value in the
    ``users`` table, ignores anything that doesn't match ``^KCET\\d{4}$``,
    and returns ``KCET<max+1>`` zero-padded.  When the table is empty the
    first issued ID is ``KCET0001``.
    """

    rows = session.execute(
        select(User.kcet_student_id).where(User.kcet_student_id.is_not(None))
    ).all()

    max_seq = 0
    for (raw,) in rows:
        n = parse_kcet_id(raw)
        if n is not None and n > max_seq:
            max_seq = n
    return format_kcet_id(max_seq + 1)


__all__ = [
    "KCET_ID_RE",
    "format_kcet_id",
    "next_kcet_id",
    "parse_kcet_id",
]
