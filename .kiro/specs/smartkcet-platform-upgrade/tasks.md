# Implementation Plan: SmartKCET Platform Upgrade

## Overview

Convert the feature design into a series of prompts for a code-generation LLM that will implement each step with incremental progress. Make sure that each prompt builds on the previous prompts, and ends with wiring things together. There should be no hanging or orphaned code that isn't integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing code.

This plan upgrades the existing FastAPI + vanilla-JS ExamForge AI codebase into the multi-subject, multi-role SmartKCET platform described in `design.md`. The implementation language is **Python 3.10+** for the backend (FastAPI, Pydantic, SQLAlchemy, Hypothesis) and **vanilla JavaScript / HTML5 / CSS3** for the frontend (fast-check for property tests). All tasks preserve the existing UI tokens, navbar classes, KPI tiles, and chart components per REQ-15. Property tests use the property numbers from `design.md` (P1–P40).

## Tasks

- [x] 1. Establish backend module layout and DB schema
  - [x] 1.1 Refactor `backend/app.py` into a package skeleton
    - Create `backend/smartkcet/` package with submodules `auth/`, `rag/`, `submissions/`, `leaderboard/`, `admin/`, `db/`, `routes/`, `middleware/`, `config.py`, `main.py`
    - Move existing FastAPI app initialisation, `VectorStore`, OCR/parsing helpers, and Groq client wiring from `backend/app.py` into the appropriate submodules
    - Keep `backend/app.py` as a thin entry-point that imports `smartkcet.main:app` and runs Uvicorn
    - Update `backend/requirements.txt` to add `sqlalchemy`, `alembic`, `bcrypt` (or `argon2-cffi`), `pyjwt`, `email-validator`, `hypothesis`, `pytest`, `pytest-asyncio`, `httpx`
    - _Requirements: 14.1, 14.2_

  - [x] 1.2 Define SQLAlchemy models for the relational schema
    - Create `backend/smartkcet/db/models.py` with `User`, `Question`, `Exam`, `ExamSet`, `ExamSetQuestion`, `Submission`, `LeaderboardScore`, `RevokedToken` ORM models matching the ER diagram in design.md §Data Models
    - Add `Subject` enum (`Biology`, `Physics`, `Chemistry`, `Mathematics`) with a CHECK constraint
    - Add unique constraints on `users.email` and `users.kcet_student_id`; add `is_eligible` column to `leaderboard_scores`
    - Create `backend/smartkcet/db/session.py` with engine/session factory (SQLite for dev, configurable via `DATABASE_URL`)
    - _Requirements: 14.1, 14.2_

  - [x] 1.3 Set up Alembic migrations and seed script
    - Initialise Alembic in `backend/migrations/`
    - Create initial migration for all tables in 1.2
    - Create `backend/smartkcet/db/seed.py` that creates the single admin account from `ADMIN_EMAIL` / `ADMIN_PASSWORD_HASH` env vars
    - _Requirements: 3.5, 14.2_

- [x] 2. Implement Auth_Service (registration, student login, admin login)
  - [ ] 2.1 Implement KCET_Student_ID generator and password hashing helpers
    - Create `backend/smartkcet/auth/identity.py` with `next_kcet_id(session)` returning the next zero-padded ID in format `KCET\d{4}`
    - Create `backend/smartkcet/auth/passwords.py` wrapping bcrypt/argon2 with `hash_password` and `verify_password`
    - Expose a module-level `HASHING_INVOKED` test hook (e.g., a `Counter` or `Mock`) so property tests can observe whether hashing was called
    - _Requirements: 1.1, 1.5, 1.6_

  - [ ]* 2.2 Write property tests for KCET_Student_ID and hashing
    - **Property 1: Registration round-trip and hashing invariants**
    - **Validates: Requirements 1.1, 1.5, 1.6**
    - File: `backend/tests/test_auth_identity.py`

  - [x] 2.3 Implement registration endpoint with pre-hash duplicate check
    - Add `POST /api/auth/register` in `backend/smartkcet/auth/routes.py`
    - Validate email (RFC 5322, ≤254 chars), password (≥8 chars, ≥1 digit), display_name (1–50 chars) BEFORE any DB call
    - Run duplicate-email `SELECT` BEFORE invoking `hash_password`; return 409 and short-circuit if duplicate
    - Persist user with role=`student` and freshly generated `KCET_Student_ID` in a single transaction
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [ ]* 2.4 Write property test for duplicate-email short-circuit
    - **Property 2: Duplicate-email check skips password hashing**
    - **Validates: Requirements 1.2**
    - File: `backend/tests/test_auth_register.py`
    - Use `unittest.mock` on `passwords.hash_password` to assert `call_count == 0` for duplicate-email cases

  - [x] 2.5 Implement student login with lockout and generic failure response
    - Add `POST /api/auth/login` issuing JWT (HS256) with claims `{sub: kcet_id, role: "student", iat, exp, jti}` and `exp - iat ≤ 86400`
    - Maintain `users.failed_login_count` and `users.lockout_until` per the table in design.md §1.5; lock after 5 consecutive failures for 15 minutes
    - Return byte-identical 401 body for "wrong password" and "unregistered email" cases
    - Set token in `httpOnly` cookie (no localStorage)
    - _Requirements: 2.1, 2.2, 2.5, 2.6, 14.5_

  - [ ]* 2.6 Write property tests for student login behaviour
    - **Property 3: Generic authentication failure for student login**
    - **Property 4: Session_Token lifetime bounds (student ≤24h)**
    - **Property 5: Lockout after 5 failed attempts**
    - **Validates: Requirements 2.2, 2.5, 2.6**
    - File: `backend/tests/test_auth_login.py`

  - [x] 2.7 Implement admin login with no-token-on-failure guarantee
    - Add `POST /api/auth/admin/login` reading `ADMIN_EMAIL` and `ADMIN_PASSWORD_HASH` from config
    - Use a single `issue_token(...)` call site gated on full credential match; no fallback path on failure
    - Issue admin JWT with `role=admin`, `exp - iat ≤ 28800` (8 hours)
    - Ensure failure response sets no `Set-Cookie` session cookie of any kind
    - _Requirements: 3.1, 3.2_

  - [ ]* 2.8 Write property tests for admin login
    - **Property 4: Session_Token lifetime bounds (admin ≤8h)**
    - **Property 7: Invalid admin credentials issue NO Session_Token of any kind**
    - **Validates: Requirements 3.1, 3.2**
    - File: `backend/tests/test_auth_admin_login.py`
    - Spy on token-issuance function to assert it is never called for invalid credentials

  - [x] 2.9 Implement logout and token revocation
    - Add `POST /api/auth/logout` that records `jti` in `revoked_tokens` and clears the cookie
    - Add token-validation helper that rejects revoked `jti`
    - _Requirements: 2.7_

  - [ ]* 2.10 Write property test for logout invalidation
    - **Property 6: Logout invalidates the token**
    - **Validates: Requirements 2.7**
    - File: `backend/tests/test_auth_logout.py`

- [x] 3. Implement RBAC middleware, startup guard, and routing layer
  - [x] 3.1 Implement startup config guard
    - Create `backend/smartkcet/config.py` reading `ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`, `JWT_SECRET`, `DATABASE_URL` at startup
    - On missing or malformed config, log a fatal error and call `sys.exit(1)` BEFORE Uvicorn starts accepting connections
    - Once the guard passes, do not impose any per-request "warming up" gate
    - _Requirements: 3.5_

  - [ ]* 3.2 Write property test for startup gate scoping
    - **Property 8: Startup gate is scoped only to malformed admin configuration**
    - **Validates: Requirements 3.5**
    - File: `backend/tests/test_startup_guard.py`

  - [x] 3.3 Implement RBAC middleware
    - Create `backend/smartkcet/middleware/rbac.py` with FastAPI dependencies `require_student()`, `require_admin()`, `require_authenticated()`
    - Read `Session_Token` from `httpOnly` cookie; resolve role; return 401 for missing/malformed/expired, 403 for role mismatch, redirect for browser navigation routes
    - Add helper `current_user_id(request)` that returns the KCET_Student_ID from the token for use by data-scoping queries
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 4.6, 4.7_

  - [ ]* 3.4 Write property tests for RBAC enforcement
    - **Property 9: Invalid Session_Tokens are rejected on protected endpoints**
    - **Property 10: Student-role tokens are denied on admin operations**
    - **Property 12: Cross-student data access is denied**
    - **Validates: Requirements 2.4, 4.2, 4.3, 4.5, 4.6, 4.7, 9.8, 10.1**
    - File: `backend/tests/test_rbac.py`

  - [x] 3.5 Implement admin redirect rule and route registration
    - Wire student/admin landing redirects: admin hitting `/dashboard` is redirected to `/admin`; student hitting `/admin/*` is redirected to `/dashboard`
    - Mount routers under `/api/auth`, `/api/admin`, `/api/student`, `/api/health` in `backend/smartkcet/main.py`
    - _Requirements: 3.3, 3.4, 4.7_

- [x] 4. Refactor RAG_Backend for per-subject isolation and transactional generation
  - [x] 4.1 Implement per-subject FAISS vector stores
    - In `backend/smartkcet/rag/store.py`, change the singleton `VectorStore` into `SubjectVectorStores` keyed by `Subject`
    - `add(subject, texts)` mutates only the index for that subject; `search(subject, query, k)` only searches that subject's index
    - Persist FAISS indexes per subject under `backend/data/faiss/{subject}.index` with chunks in `{subject}.chunks.json`
    - _Requirements: 5.1, 8.5_

  - [ ]* 4.2 Write property test for per-subject FAISS isolation
    - **Property 13: Per-subject FAISS isolation on upload**
    - **Validates: Requirements 5.1**
    - File: `backend/tests/test_rag_isolation.py`

  - [x] 4.3 Implement admin upload endpoint with required subject and OCR-warning aggregation
    - Add `POST /api/admin/upload` (admin-only) accepting `files` (≤10) and a required `subject` form field
    - Reject if no subject; index only into the selected subject's FAISS store
    - Continue processing readable files when one file produces no extractable text after OCR; return a `warnings: [filename, ...]` list in the response without aborting
    - _Requirements: 5.1, 5.3, 5.4, 8.5_

  - [ ]* 4.4 Write property test for OCR-empty file handling
    - **Property 15: OCR-empty files do not abort the upload batch**
    - **Validates: Requirements 5.4**
    - File: `backend/tests/test_rag_upload.py`

  - [x] 4.5 Implement transactional generation batch
    - Add `POST /api/admin/generate` (admin-only) with required `subject`
    - Wrap the Groq call and the 80-question insert in a single SQLAlchemy `BEGIN...COMMIT` block; tag all rows with a single `generation_batch_id`
    - On any Groq error, parse error, or insert error, `ROLLBACK` so zero rows from the failed batch persist
    - On success with zero parseable questions, commit zero rows and return a `warning` (no success confirmation)
    - Return `{added: <count>, batch_id, subject}` on success
    - _Requirements: 5.2, 5.5, 5.6, 5.7_

  - [ ]* 4.6 Write property tests for generation batch
    - **Property 14: Generation produces exactly 80 questions across 4 disjoint sets**
    - **Property 16: Groq error rolls back ALL DB writes from the generation batch**
    - **Validates: Requirements 5.2, 5.5, 7.3**
    - File: `backend/tests/test_rag_generate.py`
    - Use a mock Groq client that errors at varied stream positions

- [x] 5. Checkpoint - Auth and RAG foundations
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement Question_Bank management API
  - [x] 6.1 Implement question list endpoint with subject filter and pagination
    - Add `GET /api/admin/questions?subject={s}&page={n}` returning at most 50 questions per page plus `total` and per-subject counts
    - Default behaviour: if no subject filter is provided, return questions across all subjects (still paginated at 50)
    - _Requirements: 6.1, 6.3_

  - [ ]* 6.2 Write property test for list pagination and filtering
    - **Property 17: Question bank list respects subject filter and pagination**
    - **Validates: Requirements 6.1**
    - File: `backend/tests/test_question_bank_list.py`

  - [x] 6.3 Implement question delete endpoint with reported-status semantics
    - Add `DELETE /api/admin/questions/{id}` that returns `{deleted: true}` only when `rows_affected > 0` AND no DB error
    - On any DB error (deadlock, FK constraint), return 5xx `{deleted: false, error}` even if the underlying record may have been removed
    - _Requirements: 6.2, 6.5_

  - [x] 6.4 Implement insufficient-questions warning helper
    - Add `GET /api/admin/questions/counts` returning per-subject totals
    - Helper used by frontend to render the "fewer than 20" warning
    - _Requirements: 6.4_

- [x] 7. Implement exam creation, publish, and student exam visibility
  - [x] 7.1 Implement atomic exam-creation transaction
    - Add `POST /api/admin/exams` (admin-only) with `{subject}`
    - In a single SQL transaction: count subject questions, abort with 422 if `< 80`, randomly draw 80, partition into 4 sets of 20 with no overlap, insert 1 `exam` + 4 `exam_sets` + 80 `exam_set_questions` rows
    - On any failure at any of the three steps, `ROLLBACK` so no partial exam record persists
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 7.2 Write property test for atomic exam creation
    - **Property 20: Exam creation is an atomic transaction**
    - **Validates: Requirements 7.1**
    - File: `backend/tests/test_exam_create.py`
    - Inject failures at each of the three steps via mocks/fault injection

  - [x] 7.3 Implement publish/unpublish endpoint and exam list
    - Add `PATCH /api/admin/exams/{id}` body `{is_published: bool}` (idempotent)
    - Add `GET /api/admin/exams` returning all exams with subject, creation date, published status
    - In-progress submissions on a now-unpublished exam continue and persist normally; new attempts are blocked
    - _Requirements: 7.4, 7.5, 7.6_

  - [ ]* 7.4 Write property test for publish/unpublish
    - **Property 21: Publish/unpublish state strictly determines student availability**
    - **Validates: Requirements 7.4, 7.5**
    - File: `backend/tests/test_exam_publish.py`

  - [x] 7.5 Implement student exam-selection endpoint
    - Add `GET /api/student/exams` (student-only) returning subjects with at least one published exam, plus exam metadata per subject
    - When no published exams exist, return `{subjects: []}`
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ]* 7.6 Write property test for subject visibility
    - **Property 22: Subject visibility tied to published exams and student attempts**
    - **Validates: Requirements 8.2, 8.4**
    - File: `backend/tests/test_subject_visibility.py`

- [ ] 8. Implement Submission_Service and student exam flow
  - [x] 8.1 Implement `POST /api/student/submit` (renamed from `/analyze`)
    - Add student-auth-protected endpoint that accepts `{exam_set_id, answers, time_taken_sec}` and an idempotency key
    - Reuse the existing scoring logic from `app.py`'s `analyze` (correct/wrong/unanswered classification, topic_breakdown, recommendation text)
    - Persist `Submission` with `user_id` derived from the authenticated session token (never trust client-supplied user IDs)
    - Use the idempotency key to prevent duplicate rows on retry
    - _Requirements: 9.3_

  - [ ]* 8.2 Write property test for submission ownership
    - **Property 23: Submission is persisted under the authenticated student's ID**
    - **Validates: Requirements 9.3**
    - File: `backend/tests/test_submission_ownership.py`

  - [x] 8.3 Implement already-completed-set detection
    - Add `GET /api/student/exams/{exam_set_id}/status` that returns the student's prior `completed` submission for that set if one exists
    - The frontend uses this to render the previous-result view instead of a fresh exam attempt
    - _Requirements: 9.7_

  - [ ]* 8.4 Write property test for already-completed-set behaviour
    - **Property 26: Already-completed exam set shows previous result**
    - **Validates: Requirements 9.7**
    - File: `backend/tests/test_exam_resume.py`

  - [x] 8.5 Implement student submissions endpoint and detail endpoint
    - Add `GET /api/student/submissions` returning the authenticated student's submissions in the same shape `dashboard.js` already consumes
    - Add `GET /api/student/submissions/{id}` for the detail drawer
    - Enforce ownership: 403 if the submission does not belong to the authenticated student
    - Default sort: `submitted_at DESC`
    - _Requirements: 4.5, 10.1, 10.4, 14.3_

  - [ ]* 8.6 Write property test for default history sort
    - **Property 28: History table default sort is descending by submission timestamp**
    - **Validates: Requirements 10.4**
    - File: `backend/tests/test_submissions_sort.py`

- [ ] 9. Checkpoint - Admin and student backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implement Leaderboard_Service
  - [x] 10.1 Implement composite-score algorithm with cohort-empty fallbacks
    - Create `backend/smartkcet/leaderboard/score.py` with `compute_composite(student_stats, cohort_stats)` per design.md §6.1
    - Substitute divisor=1 when `max_attempts_in_cohort == 0` or `max_std_dev_in_cohort == 0`; consistency=100 when `attempts == 1`
    - Apply eligibility filter (`submission_count >= 1` AND `overall_average_score >= 30`) BEFORE ranking
    - _Requirements: 10.2, 11.1, 11.2_

  - [ ]* 10.2 Write property tests for composite score and eligibility
    - **Property 27: Rank "—" iff student fails leaderboard eligibility**
    - **Property 30: Composite score is well-defined for every cohort**
    - **Validates: Requirements 10.2, 11.1, 11.2**
    - File: `backend/tests/test_leaderboard_score.py`

  - [x] 10.3 Implement ranking with tie-breaking and rank-skipping
    - In `backend/smartkcet/leaderboard/rank.py`, sort eligible students by composite score descending and assign ranks with shared-rank-and-skip semantics (1, 1, 3 style)
    - _Requirements: 11.3, 11.4_

  - [ ]* 10.4 Write property test for tie-breaking
    - **Property 31: Equal Composite_Scores share rank, next rank skips**
    - **Validates: Requirements 11.3**
    - File: `backend/tests/test_leaderboard_rank.py`

  - [x] 10.5 Implement subject-filtered leaderboard
    - In the leaderboard service, support a subject filter that restricts ranking to per-subject submissions only and excludes students with zero submissions in that subject
    - _Requirements: 11.7_

  - [ ]* 10.6 Write property test for subject-filtered leaderboard
    - **Property 33: Subject-filtered leaderboard scoping**
    - **Validates: Requirements 11.7**
    - File: `backend/tests/test_leaderboard_subject.py`

  - [x] 10.7 Implement recomputation trigger gated on persisted submissions only
    - In `backend/smartkcet/submissions/service.py`, call `leaderboard.recompute_async(student_id)` only AFTER `tx.commit()` succeeds
    - Wire the recompute service so a partial-write/aborted/no-submission outcome NEVER triggers recomputation
    - Recomputation must complete within 5 seconds of submission completion
    - _Requirements: 11.6_

  - [ ]* 10.8 Write property test for recomputation trigger
    - **Property 32: Leaderboard recomputation triggers iff submission is fully persisted**
    - **Validates: Requirements 11.6**
    - File: `backend/tests/test_leaderboard_trigger.py`
    - Spy on `recompute_async` and feed random submission outcome sequences

  - [x] 10.9 Expose leaderboard endpoints
    - Add `GET /api/student/leaderboard/me` returning the authenticated student's rank, total ranked count, and top-3 medal entries
    - Add `GET /api/admin/leaderboard?subject=...` returning the full ranked list with names, KCET IDs, composite scores, subject-wise averages
    - _Requirements: 11.4, 11.5, 11.7_

- [x] 11. Implement admin analytics API
  - [x] 11.1 Implement aggregate analytics endpoint with filters
    - Add `GET /api/admin/analytics` with optional `subject`, `student`, `set`, `status` filters
    - Reshape the response to match the existing `submissions` array consumed by `dashboard.js` so chart code is reused unchanged
    - Empty filtered subset → return `{empty: true, ...}` so the frontend can render the empty-state message instead of empty charts
    - _Requirements: 12.1, 12.2, 12.3, 12.6_

  - [ ]* 11.2 Write property test for analytics filter consistency
    - **Property 37: Admin analytics filter consistency**
    - **Validates: Requirements 12.2, 12.5, 12.6**
    - File: `backend/tests/test_admin_analytics.py`

- [x] 12. Build new frontend pages (landing, login, register)
  - [x] 12.1 Create `frontend/html/landing.html` Landing_Page
    - Sections: introduction, features, KCET subject info (Biology, Physics, Chemistry, Mathematics), login CTA, register CTA
    - Link `<link rel="stylesheet" href="../css/style.css">`
    - No inline `style="color: ..."`, no inline `style="font-family: ..."`, no class definitions duplicating or overriding `style.css` classes
    - Reuse `.navbar`, `.nav-brand`, `.brand-icon`, `.section-card`, `.btn-primary`, `.btn-outline`, `.bg-mesh` from `style.css`
    - Add a small bootstrap script that reads the auth cookie and redirects authenticated students to `/dashboard` and authenticated admins to `/admin`
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 15.5_

  - [ ]* 12.2 Write property test for landing page CSS hygiene
    - **Property 38: Landing page CSS follows best-practice invariants**
    - **Validates: Requirements 13.3**
    - File: `frontend/tests/landing.css.test.js` (use fast-check + jsdom or HTML AST parser)

  - [x] 12.3 Create `frontend/html/login.html` and `frontend/html/register.html`
    - Both pages link `style.css` and reuse `.section-card`, `.text-input`, `.input-label`, `.btn-primary`, `.btn-outline`, `.navbar`, `.bg-mesh`
    - Login page submits to `/api/auth/login` (student) and offers a separate "Admin login" link that posts to `/api/auth/admin/login`
    - Register page submits to `/api/auth/register` and shows the assigned `KCET_Student_ID` on success
    - On 423 (lockout), show the remaining wait time
    - On 409 (duplicate email), show "email already registered" without exposing other validation state
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.6, 3.1_

  - [x] 12.4 Create shared `frontend/js/auth.js` client module
    - Export `login(email, password)`, `adminLogin(email, password)`, `register({email, password, displayName})`, `logout()`, `currentRole()`, `redirectIfAuthenticated()`
    - Calls all use `credentials: 'include'` so the `httpOnly` cookie is sent; tokens are NEVER read from or written to `localStorage`
    - Wire `login.html`, `register.html`, and the bootstrap on `landing.html` to this module
    - _Requirements: 2.3, 2.4, 2.7, 14.5_

  - [ ]* 12.5 Write property test for localStorage hygiene
    - **Property 34: localStorage size bound and no-token invariant**
    - **Validates: Requirements 14.5**
    - File: `frontend/tests/storage.test.js`

- [x] 13. Build admin panel pages and wire admin endpoints
  - [x] 13.1 Move existing generator UI to `frontend/html/admin-upload.html`
    - Copy the upload drag-and-drop, file cards, upload progress bar, and generation progress steps from `frontend/html/index.html` into `admin-upload.html`
    - Add a required subject `<select>` with the four subjects above the upload zone
    - Link `style.css`; reuse all existing CSS classes
    - _Requirements: 5.8, 8.5, 15.5_

  - [x] 13.2 Create `frontend/html/admin-questions.html` (Question_Bank management)
    - Build a table reusing `.results-table` showing 50 questions per page with subject filter, total count per subject, and a delete button with explicit confirmation
    - The delete button removes the row from the panel within 2 seconds ONLY when `DELETE` returns `{deleted: true}`; otherwise keep the row visible and show an error
    - Show an "insufficient questions" warning when subject count < 20; remove it when ≥ 20
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 13.3 Write property tests for question-bank UI behaviours
    - **Property 18: Question deletion UI follows the DB-reported status**
    - **Property 19: Insufficient-question warning threshold at 20**
    - **Validates: Requirements 6.2, 6.4, 6.5**
    - File: `frontend/tests/admin-questions.test.js` (mock fetch returning success/failure across many ids)

  - [x] 13.4 Create `frontend/html/admin-exams.html` (exam creation and publish)
    - List all exams with subject, creation date, published/unpublished status using `.results-table`
    - "Create exam" button calls `POST /api/admin/exams`; show 422 messaging when subject has < 80 questions
    - Publish/unpublish toggles call `PATCH /api/admin/exams/{id}`
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 7.6_

  - [x] 13.5 Refactor `frontend/js/app.js` admin upload/generate logic
    - Repoint `RAG.uploadDocs` and `RAG.generate` to `/api/admin/upload` and `/api/admin/generate`
    - Send `subject` field with both calls; require subject selection before either call fires
    - Read auth from cookie (no localStorage `ragConfig` for endpoint); the endpoint becomes a constant `/api`
    - On generation success, show `{added: N}` confirmation in the admin panel; on zero-question completion, show the warning state
    - _Requirements: 5.6, 5.7, 8.5, 14.5_

- [x] 14. Refactor student dashboard and exam pages
  - [x] 14.1 Refactor `frontend/js/dashboard.js` to use `/api/student/submissions`
    - Replace `Store.get('submissions')` with `await fetch('/api/student/submissions', {credentials:'include'}).then(r=>r.json())`
    - Hide the `#filterStudent` dropdown for student users (it remains on the admin analytics page)
    - Add `#filterSubject` dropdown populated from the subjects the student has attempted; pipe through existing radar/bar/doughnut chart code unchanged
    - Reuse the existing AI analysis block (`#aiBlock`) with the existing 70 / 40 thresholds
    - Restrict `#rankingBody` to top 3 with medal indicators
    - Add a "Your Rank" KPI card; show `—` when ineligible with the hint "score at least 30% on average to enter the leaderboard"
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.4, 14.3_

  - [ ]* 14.2 Write property tests for dashboard rank and AI tier rendering
    - **Property 27: Rank "—" iff student fails leaderboard eligibility (UI side)**
    - **Property 29: AI analysis tier classification**
    - **Validates: Requirements 10.2, 10.5, 11.2**
    - File: `frontend/tests/dashboard.test.js`

  - [x] 14.3 Refactor `frontend/js/exam.js` for server-driven exam loading
    - Replace `Store.get('examConfig')` with `await fetch('/api/student/exams/{id}', {credentials:'include'})` to load questions from the DB
    - Add 60-minute countdown that calls `submitPaper()` automatically when it reaches zero
    - Before showing the exam, call `GET /api/student/exams/{exam_set_id}/status`; if a completed submission exists, render the previous-result view instead of the exam UI
    - Replace `Store.set('submissions', ...)` with `POST /api/student/submit`; on success redirect to `/dashboard`
    - Send a client-generated UUID idempotency key so retries don't create duplicates
    - _Requirements: 9.1, 9.2, 9.3, 9.5, 9.6, 9.7, 9.8, 14.5_

  - [ ]* 14.4 Write property tests for exam-flow UI rules
    - **Property 25: Timer-expiry auto-submits the current answer state**
    - **Property 26: Already-completed exam set shows previous result (UI side)**
    - **Validates: Requirements 9.6, 9.7**
    - File: `frontend/tests/exam.test.js`

  - [x] 14.5 Implement retry-then-redirect submission flow with offline queue
    - On `POST /api/student/submit` 5xx, keep the user on the exam page with a "retry" UI; only redirect to `/dashboard` after a successful persistence (initial or retry)
    - When the DB is unavailable, queue up to 3 submissions in `localStorage` under key `ef_submission_queue` with `{id, exam_set_id, answers, queued_at, attempts, last_attempt_at}`
    - Retry every 30 seconds, max 10 attempts per submission
    - Show a status indicator with pending count and last-retry timestamp
    - When retry exhausts AND `attempts >= 1`, show the manual retry prompt (`#manual-retry-prompt`); preserve queued data; never display the prompt when the queue is empty or no attempt has been made
    - _Requirements: 9.4, 9.5, 14.5, 14.6, 14.7_

  - [ ]* 14.6 Write property tests for submission queue and retry policy
    - **Property 24: Redirect to dashboard iff submission has been persisted (retry-then-redirect)**
    - **Property 35: Submission queue length and retry policy**
    - **Property 36: Manual retry prompt is gated by attempted-and-exhausted**
    - **Validates: Requirements 9.4, 9.5, 14.6, 14.7**
    - File: `frontend/tests/submission-queue.test.js`

- [x] 15. Build admin analytics page
  - [x] 15.1 Create `frontend/html/admin-analytics.html` and `frontend/js/admin-analytics.js`
    - Reuse the DOM structure of `dashboard.html` and the rendering code in `dashboard.js`: same `.section-card`, `.kpi-tile`, `.chart-card`, `.results-table`, `.detail-drawer` classes
    - Show the `#filterStudent` dropdown (hidden on student dashboard); keep `#filterSubject`, `#filterSet`, `#filterStatus`
    - Show the full ranked leaderboard table in addition to the top-3 medal display
    - Detail drawer opens for any student's submission
    - CSV export reuses existing `exportReport()`; disabled when filtered set is empty
    - When filtered subset is empty, show empty-state message and do NOT render charts with empty data
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 11.5, 15.3_

- [x] 16. Routing, root-path redirects, and config.html compliance
  - [x] 16.1 Wire root-path routing
    - Configure FastAPI/static-server so `/` and `/index.html` serve `landing.html` for unauthenticated visitors
    - Authenticated student GET `/` → 302 to `/dashboard`; authenticated admin GET `/` → 302 to `/admin/upload`
    - The historical generator UI is now reachable only via `/admin/upload` behind admin auth
    - _Requirements: 13.5, 13.6_

  - [ ]* 16.2 Write property test for root-path redirects
    - **Property 40: Routing redirects at root path follow viewer role**
    - **Validates: Requirements 13.5, 13.6**
    - File: `backend/tests/test_root_routing.py`

  - [x] 16.3 Bring `frontend/html/config.html` into style.css compliance
    - Remove the inline `<style>` block
    - Add `<link rel="stylesheet" href="../css/style.css">`
    - Remap classes (`.config-container` → `.section-card`, `.btn-primary` already exists, etc.) so all visual styles come from `style.css` only
    - Convert `config.html` into an admin-token-protected developer diagnostic page; non-admins are redirected to `/login`
    - Preserve user-facing behaviour (test connection, save endpoint) but drive auth via the admin cookie
    - _Requirements: 4.4, 15.5, 15.6_

  - [x] 16.4 Update existing `index.html`, `exam.html`, `dashboard.html` for auth-aware navigation
    - Replace the static `Settings` link with a role-aware nav: students see `Dashboard | Logout`; admins see `Generator | Question Bank | Exams | Analytics | Logout`
    - Add `.nav-links` class as a synonym alongside `.nav-center` in `style.css` (no removal) so the navbar manifest in REQ-15.2 is satisfied verbatim
    - Ensure no admin-only DOM elements (upload/generate/question-bank UI) are rendered on student-facing pages
    - _Requirements: 4.4, 15.2_

  - [ ]* 16.5 Write property test for admin-UI rendering rules
    - **Property 11: Admin UI is never rendered to students or unauthenticated visitors**
    - **Validates: Requirements 4.4**
    - File: `backend/tests/test_admin_ui_rendering.py` (request HTML responses with various tokens, assert absence of admin-only nodes)

- [ ] 17. Implement build-time CSS link enforcement and class-removal guards (REQ-15)
  - [ ] 17.1 Capture baseline snapshots
    - Create `tests/baseline/css_classes.json` listing every CSS class declared in the current `style.css` and used in the current `index.html`, `exam.html`, `dashboard.html`, `config.html`
    - Create `tests/baseline/css_root_tokens.json` capturing the `:root` block from `style.css` as a `{name: value}` map
    - Create `tests/baseline/bg_mesh.json` capturing the literal `.bg-mesh` background-image declaration
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.6_

  - [ ] 17.2 Implement the build-time CSS link enforcement script
    - Create `tests/build/check_css_link.py` (run via `pytest`) that scans every `frontend/html/*.html` file (existing AND new), asserts each contains a `<link rel="stylesheet" href=".../style.css">` reference, and asserts no page declares a class that duplicates or overrides a class defined in `style.css`
    - Failure must mark the build as failed (non-zero exit)
    - Wire this script into `pytest` so it runs on every CI build, not only on additions
    - _Requirements: 15.5_

  - [ ]* 17.3 Write property test for CSS link enforcement
    - **Property 39: Build-time CSS link enforcement on every page**
    - **Validates: Requirements 15.5**
    - File: `tests/build/test_css_link_enforcement.py`
    - Generator: enumerate `frontend/html/*.html` and apply random mutations (remove link, override class) to assert the check fails

  - [ ] 17.4 Implement CSS-token and class-removal guards
    - Create `tests/test_style_tokens.py` that parses `:root` from `style.css` and asserts every name in `tests/baseline/css_root_tokens.json` is still present with its baseline value (additions allowed, removals/changes fail)
    - Create `tests/test_class_removal_guard.py` that asserts the union of baseline classes is a subset of the current build's class set
    - Create `tests/test_bg_mesh.py` asserting the `.bg-mesh` declaration matches the baseline byte-for-byte
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.6_

- [x] 18. Final integration and wiring
  - [x] 18.1 Wire the navbar across all pages with role-aware links
    - Update navbars in `landing.html`, `login.html`, `register.html`, `dashboard.html`, `exam.html`, `admin-upload.html`, `admin-questions.html`, `admin-exams.html`, `admin-analytics.html`, `config.html` to use `.navbar`, `.nav-brand`, `.brand-icon`, `.nav-links`, `.nav-pill`, `.nav-pill.active`, `.rag-status`, `.status-dot`, `.status-text`, `.nav-actions`
    - Add a logout pill that POSTs to `/api/auth/logout` and redirects to `/login`
    - _Requirements: 2.7, 15.2_

  - [x] 18.2 Wire the `Subject` selector throughout the student exam flow
    - On `/dashboard`, surface the four-subject filter; on `/exam`, surface the subject + set picker that calls `GET /api/student/exams`
    - Ensure subjects with no published exam are not shown
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 18.3 Add DB-unavailable login error handling
    - In `frontend/js/auth.js`, surface a clear error message when login receives a DB-unreachable error and block dashboard access until connectivity is restored
    - In the backend, ensure `POST /api/auth/login` returns a 503 with a structured error when the DB pool is unavailable
    - _Requirements: 14.4_

  - [x] 18.4 Migrate any pre-existing `localStorage` submission data
    - On first load after upgrade, detect legacy `ef_submissions` entries and queue them for upload to `/api/student/submit` once the user is authenticated
    - On successful upload, clear the legacy key
    - _Requirements: 14.1_

- [ ] 19. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional property/unit tests that can be skipped for a faster MVP, but they are the canonical machine-verifiable checks for the design's correctness properties (P1–P40).
- Each task references specific requirements (REQ-X.Y) for full traceability.
- Property tests use Hypothesis (Python) for backend invariants and fast-check (JavaScript) for frontend invariants, each with `max_examples / numRuns ≥ 100`.
- Top-level tasks 5, 9, and 19 are checkpoints to validate progress before moving on.
- The build-time CSS link enforcement (task 17.2) runs on every build, not only when new pages are added, satisfying the strict reading of REQ-15.5.
- Existing JavaScript utilities (`Store`, `RAG`, `localAnalyze`, chart-rendering helpers) are preserved and repurposed; the upgrade does not rewrite them.
- All visual elements (`.navbar`, `.kpi-tile`, `.chart-card`, `.section-card`, `.results-table`, `.detail-drawer`, `.bg-mesh`) are reused from `style.css` per REQ-15.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "17.1"] },
    { "id": 2, "tasks": ["1.3", "2.1", "3.1", "4.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.2", "3.3", "4.2", "4.3"] },
    { "id": 4, "tasks": ["2.4", "2.5", "2.7", "2.9", "3.4", "3.5", "4.4", "4.5", "10.1", "10.3"] },
    { "id": 5, "tasks": ["2.6", "2.8", "2.10", "4.6", "6.1", "6.3", "6.4", "7.1", "10.2", "10.4", "10.5"] },
    { "id": 6, "tasks": ["6.2", "7.2", "7.3", "7.5", "8.1", "8.3", "8.5", "10.6", "10.7", "11.1"] },
    { "id": 7, "tasks": ["7.4", "7.6", "8.2", "8.4", "8.6", "10.8", "10.9", "11.2", "13.1", "13.4", "13.5", "16.3"] },
    { "id": 8, "tasks": ["12.1", "12.3", "12.4", "13.2", "14.1", "14.3", "15.1", "16.1", "16.4", "17.2", "17.4"] },
    { "id": 9, "tasks": ["12.2", "12.5", "13.3", "14.2", "14.4", "14.5", "16.2", "16.5", "17.3", "18.1", "18.2", "18.3", "18.4"] },
    { "id": 10, "tasks": ["14.6"] }
  ]
}
```
