"""RAG pipeline package.

Houses the FAISS vector store, document parsing helpers (PDF/DOCX/TXT with
OCR fallback), the MCQ extractor, and the Groq LLM client wiring that
previously lived inside ``backend/app.py``.

Per-subject vector store isolation (design.md §5) lands in task 4.1; for
now the package exposes a single global :class:`~.store.VectorStore`
instance via :data:`smartkcet.rag.store.store` to preserve current behaviour.
"""

from . import groq_client, mcq_extractor, parsing, store  # noqa: F401  (re-exported for callers)

__all__ = ["groq_client", "mcq_extractor", "parsing", "store"]
