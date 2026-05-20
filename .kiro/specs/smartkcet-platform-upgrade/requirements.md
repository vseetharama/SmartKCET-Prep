# Requirements Document

## Introduction

This document defines the requirements for upgrading the existing **ExamForge AI / SmartKCET Prep** platform from a single-user, Biology-only question generator into a full multi-subject KCET exam preparation platform with student authentication, an admin control panel, a leaderboard, and subject-wise analytics.

**Current system summary (as-is):**
- Frontend: 4 HTML pages (`index.html`, `exam.html`, `dashboard.html`, `config.html`) with a shared dark-theme CSS (`style.css`) and vanilla JavaScript.
- Backend: Python FastAPI (`app.py`) with FAISS vector store, Groq LLM (llama-3.3-70b-versatile), Sentence Transformers, OCR pipeline, and three endpoints: `POST /upload`, `POST /generate`, `POST /analyze`.
- Data persistence: `localStorage` only (no server-side database).
- Current flow: Any user uploads PDFs → backend generates 4 MCQ sets → user takes exam → results stored in `localStorage` → dashboard reads from `localStorage`.
- Subject support: Biology only (inferred from uploaded content).
- No authentication, no roles, no persistent user accounts.

**Upgrade goals:**
1. Add student login/registration with auto-generated KCET student IDs.
2. Restrict upload/generate to admin only; students only take pre-generated exams.
3. Expand subject support to Biology, Physics, Chemistry, and Mathematics.
4. Add a persistent backend database for questions, users, and results.
5. Add a ranking/leaderboard system.
6. Preserve all existing UI, CSS, theme, animations, and layout.

---

## Glossary

- **Platform**: The ExamForge AI / SmartKCET Prep web application as a whole.
- **Student**: An end-user who registers with a personal email, receives a KCET Student ID, and takes exams.
- **Admin**: A privileged user who uploads study materials, generates questions, manages the question bank, creates exams, and monitors analytics.
- **KCET_Student_ID**: A unique auto-generated identifier in the format `KCET0001`, `KCET0002`, etc., assigned to each registered student.
- **Question_Bank**: The server-side persistent store of all admin-generated MCQ questions, organised by subject.
- **Exam**: A timed or untimed set of questions drawn from the Question_Bank for a specific subject, made available to students by the Admin.
- **Subject**: One of the four KCET subjects: Biology, Physics, Chemistry, or Mathematics.
- **Submission**: A student's completed exam attempt, including answers, score, time taken, and topic breakdown.
- **Leaderboard**: A ranked list of students ordered by composite performance score.
- **Composite_Score**: A numeric value computed from a student's average exam score, consistency (standard deviation of scores), and number of attempts.
- **Admin_Panel**: A restricted set of pages accessible only to Admin users for content management and analytics.
- **Student_Dashboard**: A personalised analytics page visible only to the logged-in Student, showing their own performance, rank, and exam history.
- **RAG_Backend**: The existing FastAPI backend that handles PDF ingestion, vector search, and LLM-based question generation.
- **Auth_Service**: The new backend module responsible for user registration, login, session management, and role enforcement.
- **DB**: The new server-side persistent database (e.g., SQLite or PostgreSQL) that stores users, questions, exams, and submissions.
- **Landing_Page**: A new public-facing page that introduces the platform, its features, and KCET subject information, with links to login/register.
- **Session_Token**: A short-lived JWT or equivalent credential issued on login and used to authenticate subsequent API requests.

---

## Requirements

### Requirement 1: Student Registration

**User Story:** As a prospective student, I want to register with my personal email address, so that I can access the KCET exam preparation platform.

#### Acceptance Criteria

1. WHEN a visitor submits a registration form with an email address conforming to RFC 5322 format (maximum 254 characters) and a valid password, and a display name between 1 and 50 characters, THE Auth_Service SHALL create a new Student account and assign a unique KCET_Student_ID in the format `KCET` followed by a zero-padded 4-digit sequence number (e.g., `KCET0001`).
2. WHEN a visitor submits a registration form, THE Auth_Service SHALL check for a duplicate email in the DB before performing any password hashing, AND IF the email already exists, THEN THE Auth_Service SHALL return an error message stating the email is already registered without invoking the password-hashing routine.
3. WHEN a visitor submits a registration form with an email address that does not conform to RFC 5322 format or exceeds 254 characters, THE Auth_Service SHALL return a validation error before contacting the DB and SHALL block account creation.
4. WHEN a visitor submits a registration form with a password shorter than 8 characters or containing no digits, THE Auth_Service SHALL return a validation error before contacting the DB and SHALL block account creation.
5. THE Auth_Service SHALL store passwords as salted cryptographic hashes and SHALL NOT store plaintext passwords.
6. WHEN a new Student account is created, THE DB SHALL persist the student's email, KCET_Student_ID, display name (1–50 characters, visitor-provided), registration timestamp, and hashed password.

---

### Requirement 2: Student Login

**User Story:** As a registered student, I want to log in with my personal email and password, so that I can access my personalised exam dashboard.

#### Acceptance Criteria

1. WHEN a student submits a login form with an email address in `local@domain.tld` format and a non-empty password field that match a registered account, THE Auth_Service SHALL issue a Session_Token and redirect the student to the Student_Dashboard.
2. WHEN a student submits an incorrect password or unregistered email, THE Auth_Service SHALL return a generic authentication failure message without revealing which field is incorrect.
3. WHILE a student holds a valid Session_Token, THE Platform SHALL maintain the student's authenticated session across page navigations, browser refresh, and back/forward actions.
4. WHEN a Session_Token expires or is invalidated, THE Platform SHALL redirect the student to the login page.
5. THE Auth_Service SHALL enforce a Session_Token lifetime of no more than 24 hours.
6. WHEN a student makes 5 consecutive failed login attempts for the same email address, THE Auth_Service SHALL lock that account for 15 minutes and SHALL return a lockout message indicating the remaining wait time.
7. WHEN a student explicitly logs out, THE Auth_Service SHALL immediately invalidate the Session_Token and redirect the student to the login page.

---

### Requirement 3: Admin Login

**User Story:** As an admin, I want to log in with admin credentials, so that I can access the Admin_Panel to manage content and monitor students.

#### Acceptance Criteria

1. WHEN an admin submits valid admin credentials, THE Auth_Service SHALL issue a Session_Token with an admin role claim, valid for no more than 8 hours, and redirect the admin to the Admin_Panel.
2. WHEN an admin submits invalid admin credentials, THE Auth_Service SHALL return a generic authentication failure message without revealing which field is incorrect AND SHALL NOT issue any Session_Token (with or without admin role) for that authentication attempt.
3. WHEN a student attempts to access any Admin_Panel route, THE Auth_Service SHALL deny access and redirect the student to the Student_Dashboard.
4. WHEN an admin attempts to access the Student_Dashboard, THE Platform SHALL redirect the admin to the Admin_Panel.
5. THE Platform SHALL support exactly one admin account, configured via a secure environment variable or seed script. IF the admin account environment variable is absent or malformed at application startup, THEN THE Platform SHALL log a startup error and refuse to serve any requests until the configuration is corrected. WHILE the admin configuration is present and well-formed, THE Platform SHALL continue serving requests during application startup and SHALL NOT refuse requests solely because startup is still in progress.

---

### Requirement 4: Role-Based Access Control

**User Story:** As a platform operator, I want strict role separation between students and admins, so that students cannot access or modify the question bank or admin features.

#### Acceptance Criteria

1. THE Auth_Service SHALL assign each authenticated user exactly one role: `student` or `admin`.
2. WHEN an unauthenticated request is made to any protected API endpoint, THE Auth_Service SHALL return HTTP 401.
3. WHEN a student-role Session_Token is used to call an admin-only API endpoint (upload, generate, manage question bank, view all student analytics), THE Auth_Service SHALL return HTTP 403 and SHALL NOT execute the requested operation nor return response body data.
4. WHILE a student-role session is active, THE Platform SHALL NOT render upload, generate, or question-bank management UI elements in the DOM. WHILE no user is authenticated, THE Platform SHALL still render upload, generate, and question-bank management UI elements only on admin-restricted routes (which require an admin Session_Token to load), so unauthenticated visitors never receive these elements in the DOM.
5. IF a student attempts to access another student's exam scores, attempt history, or performance metrics, THEN THE Platform SHALL return HTTP 403 and SHALL NOT return any of that student's data.
6. WHEN a request is made with a malformed or expired Session_Token to any protected API endpoint, THE Auth_Service SHALL return HTTP 401.
7. WHEN a student-role session is active and the student navigates directly to an Admin_Panel URL, THE Platform SHALL redirect the student to the Student_Dashboard.

---

### Requirement 5: Admin — File Upload and Question Generation

**User Story:** As an admin, I want to upload PDF/DOCX study materials and previous year papers, so that the system can generate questions for the question bank.

#### Acceptance Criteria

1. WHEN an admin uploads one or more files (PDF, DOCX, or TXT) and selects a Subject, THE RAG_Backend SHALL index the file content into a FAISS vector store scoped exclusively to that Subject, without modifying the vector stores of any other Subject.
2. WHEN an admin triggers question generation for a Subject, THE RAG_Backend SHALL generate exactly 80 MCQ questions (4 sets × 20 questions) using the existing Groq LLM pipeline and append the resulting questions to the Question_Bank under the selected Subject, preserving any previously stored questions for that Subject.
3. THE RAG_Backend SHALL accept a maximum of 10 files per upload batch, consistent with the existing limit.
4. IF an uploaded file contains no extractable text after OCR processing, THEN THE RAG_Backend SHALL return a warning message identifying the unreadable file without aborting the entire batch.
5. IF the Groq API returns an error during question generation, THEN THE RAG_Backend SHALL return an error response AND SHALL roll back all database writes performed during the current generation batch (including any questions, exam-set rows, or partial records written before the error) so that no records from the failed batch remain in the Question_Bank.
6. WHEN questions are successfully generated and stored, THE Admin_Panel SHALL display a confirmation showing the number of questions added to the Question_Bank for the selected Subject.
7. WHEN question generation completes but zero questions are produced, THE Admin_Panel SHALL NOT display a success confirmation and SHALL display a warning indicating no questions were generated.
8. THE Admin_Panel SHALL retain the functional behaviour of the existing upload drag-and-drop zone, file cards, upload progress bar, and generation progress steps from the current `index.html` interface.

---

### Requirement 6: Admin — Question Bank Management

**User Story:** As an admin, I want to view and manage the stored question bank, so that I can ensure question quality and remove outdated questions.

#### Acceptance Criteria

1. WHEN an admin opens the Question Bank view, THE Admin_Panel SHALL display all questions in the Question_Bank filtered to the currently selected Subject (defaulting to all subjects), paginated at 50 questions per page.
2. WHEN an admin confirms deletion of a question from the Question_Bank, THE Admin_Panel SHALL treat the operation as successful only if the DB delete operation reports success, AND in that case THE DB SHALL remove that question and THE Admin_Panel SHALL reflect the removal within 2 seconds without a full page reload. IF the DB delete operation reports failure (regardless of whether the underlying record was actually removed), THEN THE Admin_Panel SHALL treat the operation as failed and SHALL keep the question visible in the panel. THE Admin_Panel SHALL require an explicit confirmation step before executing the deletion.
3. THE Admin_Panel SHALL show the total question count per Subject.
4. WHEN the Question_Bank for a Subject contains fewer than 20 questions, THE Admin_Panel SHALL display a warning indicating insufficient questions to create a full exam set. WHEN the count rises to 20 or more, THE Admin_Panel SHALL remove the warning.
5. IF the DB delete operation fails, THEN THE Admin_Panel SHALL display an error message and SHALL leave the question visible in the list.

---

### Requirement 7: Admin — Exam Creation

**User Story:** As an admin, I want to create and publish exam sets for students, so that students can take pre-generated exams without uploading their own files.

#### Acceptance Criteria

1. WHEN an admin creates an exam for a Subject that has at least 80 questions in the Question_Bank, THE Platform SHALL randomly draw 80 questions from the Question_Bank for that Subject, partition them into 4 sets of 20, and store the exam in the DB as a single atomic transaction such that all three steps (drawing, partitioning, and storing) succeed together or fail together. IF any of these steps fails, THEN THE Platform SHALL roll back the transaction so that no partial or incomplete exam record is persisted in the DB.
2. IF an admin attempts to create an exam for a Subject with fewer than 80 questions in the Question_Bank, THEN THE Platform SHALL block exam creation and display an error indicating the shortfall.
3. THE Platform SHALL generate 4 unique exam sets (Set A, Set B, Set C, Set D) per exam creation, each containing 20 MCQ questions with no question repeated across sets, consistent with the existing generation logic.
4. WHEN an admin publishes an exam, THE Platform SHALL make it available to all registered students for the corresponding Subject.
5. WHEN an admin unpublishes an exam, THE Platform SHALL prevent students from starting new attempts on that exam. Unpublishing always takes precedence — any exam that has been unpublished remains unavailable to students until the admin explicitly republishes it.
6. THE Admin_Panel SHALL list all created exams with their Subject, creation date, and published/unpublished status.

---

### Requirement 8: Multi-Subject Support

**User Story:** As a student, I want to select from Biology, Physics, Chemistry, and Mathematics, so that I can prepare for all KCET subjects.

#### Acceptance Criteria

1. THE Platform SHALL support exactly four subjects: Biology, Physics, Chemistry, and Mathematics.
2. WHEN a student navigates to the exam selection screen, THE Platform SHALL display only the subjects for which at least one published exam exists. WHEN no published exams exist for any subject, THE Platform SHALL display a message indicating no exams are currently available.
3. THE Question_Bank SHALL store questions with a subject tag and SHALL NOT mix questions from different subjects within a single exam set.
4. THE Student_Dashboard SHALL display performance analytics (average score, attempt count, pass rate) separately for each Subject the student has attempted. WHEN a student has not attempted any exam for a Subject, THE Student_Dashboard SHALL omit that Subject from the analytics display.
5. WHEN an admin uploads files, THE Admin_Panel SHALL require the admin to select one of the four subjects before indexing begins. IF no subject is selected, THEN THE Admin_Panel SHALL block the indexing process entirely and display a subject-selection prompt.

---

### Requirement 9: Student Exam Flow

**User Story:** As a student, I want to select a subject, choose an exam set, and take the exam, so that I can practise for KCET using admin-prepared questions.

#### Acceptance Criteria

1. WHEN a logged-in student selects a Subject and a published exam set, THE Platform SHALL load the pre-generated questions from the DB and present the exam interface within 3 seconds.
2. WHILE a student is taking an exam, THE Platform SHALL display the question navigator sidebar, progress bar, MCQ option buttons, skip functionality, a countdown timer starting from 60 minutes, and a submit confirmation modal.
3. WHEN a student submits an exam, THE Platform SHALL send the answers to the `POST /analyze` endpoint and persist the Submission (score, topic breakdown, time taken, timestamp) in the DB under the student's KCET_Student_ID.
4. IF the `POST /analyze` endpoint returns an error, THEN THE Platform SHALL display an error message to the student and SHALL NOT redirect to the Student_Dashboard until the submission is successfully persisted.
5. WHEN a student completes an exam and the Submission is successfully persisted (including cases where the `POST /analyze` endpoint initially returned an error but a subsequent retry succeeded), THE Platform SHALL redirect the student to the Student_Dashboard showing the results of that submission.
6. WHEN the countdown timer reaches zero, THE Platform SHALL automatically submit the student's current answers as a Submission.
7. WHEN a student attempts to start an exam set they have already completed, THE Platform SHALL display their previous result and offer the option to attempt a different set.
8. THE Platform SHALL NOT allow a student to upload files or trigger question generation.

---

### Requirement 10: Student Dashboard

**User Story:** As a student, I want to view my personal performance dashboard, so that I can track my progress across subjects and exam attempts.

#### Acceptance Criteria

1. WHEN a logged-in student opens the Student_Dashboard, THE Platform SHALL use the student's KCET_Student_ID from the Session_Token to scope all DB queries, ensuring only that student's own Submissions are returned.
2. THE Student_Dashboard SHALL show the following KPIs: total exams taken, average score (as a percentage, rounded to one decimal place) per Subject, overall pass rate (percentage of Submissions with score ≥ 50%), and current Leaderboard rank. WHILE a student has completed zero exams OR fails to meet the Leaderboard inclusion criteria defined in Requirement 11 (e.g., minimum-score threshold) regardless of attempt count, THE Student_Dashboard SHALL display "—" as the rank indicator and exclude the student from the Leaderboard.
3. THE Student_Dashboard SHALL display subject-wise performance using the existing radar chart (topic breakdown within a subject), bar chart (set-wise scores), and pass/fail doughnut chart components from `dashboard.js`, scoped to the currently selected Subject filter.
4. THE Student_Dashboard SHALL display the student's exam history as a sortable table showing subject, set, score (percentage), time taken, and pass/fail status, defaulting to descending sort by submission timestamp.
5. THE Student_Dashboard SHALL display the student's AI performance analysis (strong areas ≥ 70%, areas to improve 40–69%, weak areas < 40%, and recommendation text) using the existing AI analysis block from `dashboard.js`.
6. THE Platform SHALL preserve the existing dashboard CSS, card layout, KPI tiles, chart styles, and colour theme.

---

### Requirement 11: Leaderboard and Ranking System

**User Story:** As a student, I want to see a leaderboard showing top-ranked students, so that I can understand my standing relative to peers.

#### Acceptance Criteria

1. THE Platform SHALL compute a Composite_Score for each student using the formula: `(average_score × 0.6) + (attempt_count_normalised × 0.2) + (consistency_score × 0.2)`, where `attempt_count_normalised = (student_attempts / max_attempts_in_cohort) × 100` and `consistency_score = 100 - ((student_std_dev / max_std_dev_in_cohort) × 100)`. WHEN a student has exactly one attempt, consistency_score SHALL be 100. WHEN the cohort has no previous attempts (i.e., `max_attempts_in_cohort` or `max_std_dev_in_cohort` is zero), THE Platform SHALL substitute default normalisation factors of 1 for the zero divisor(s) so that `attempt_count_normalised` and `consistency_score` remain well-defined and the Composite_Score computation does not divide by zero.
2. THE Platform SHALL rank all students with at least one Submission in descending order of Composite_Score and assign integer ranks starting from 1. Students with zero Submissions SHALL be excluded from the ranked list. THE Platform SHALL also exclude from the ranked list any student whose performance fails to meet the minimum-score inclusion threshold (overall average score below 30%), regardless of their attempt count, and SHALL display "—" as the rank indicator for such excluded students.
3. WHEN two students have equal Composite_Scores, THE Platform SHALL assign them the same rank and skip the next rank number.
4. THE Student_Dashboard SHALL display the student's current rank, the total number of ranked students, and the top 3 students with medal indicators (🥇, 🥈, 🥉). WHEN fewer than 3 students are ranked, THE Student_Dashboard SHALL display only the available ranks.
5. THE Admin_Panel SHALL display the full leaderboard with all students' ranks, names, KCET_Student_IDs, Composite_Scores, and subject-wise average scores.
6. WHEN a student successfully completes a new Submission (i.e., the Submission is fully processed and persisted in the DB), THE Platform SHALL recompute that student's Composite_Score and update the leaderboard within 5 seconds of submission completion. IF submission processing fails or is incomplete (e.g., persistence error, partial write, or aborted submission), THEN THE Platform SHALL NOT trigger leaderboard recomputation. THE Platform SHALL NOT trigger leaderboard recomputation when no new Submission has occurred.
7. WHEN a Subject filter is applied to the Leaderboard, THE Platform SHALL rank students based on their average score for that Subject only, excluding students who have not attempted any exam for that Subject.

---

### Requirement 12: Admin — Student Analytics

**User Story:** As an admin, I want to monitor all students' performance across subjects, so that I can identify struggling students and improve content quality.

#### Acceptance Criteria

1. WHEN an admin opens the Analytics view, THE Admin_Panel SHALL display aggregate analytics across all students and all subjects using the existing dashboard chart components (topic radar, set-wise bar, pass/fail doughnut), defaulting to the all-subjects, all-students view.
2. WHEN an admin applies a filter (by Subject, by KCET_Student_ID or name, or by exam set), THE Admin_Panel SHALL update all charts and the results table to reflect only the matching Submissions.
3. THE Admin_Panel SHALL display the full student results table with sortable columns: student name, KCET_Student_ID, subject, set, score, time taken, and pass/fail status. The default sort order SHALL be descending by submission timestamp.
4. WHEN an admin clicks a student row, THE Admin_Panel SHALL open the existing detail drawer showing that student's answer review, topic breakdown, and AI recommendation.
5. WHEN an admin triggers CSV export, THE Admin_Panel SHALL generate and download a CSV file containing all currently filtered results, consistent with the existing `exportReport` function in `dashboard.js`. IF no results match the current filter, THE Admin_Panel SHALL disable the export button.
6. WHEN no Submissions match the current filter, THE Admin_Panel SHALL display an empty-state message and SHALL NOT render chart components with empty data.

---

### Requirement 13: Landing Page

**User Story:** As a visitor, I want to see a landing page that explains the platform, so that I can understand what SmartKCET Prep offers before registering.

#### Acceptance Criteria

1. THE Platform SHALL provide a public Landing_Page accessible without authentication.
2. THE Landing_Page SHALL include sections for: platform introduction, key features, KCET subject information (Biology, Physics, Chemistry, Mathematics), a call-to-action linking to the login page, and a separate call-to-action linking to the registration page.
3. THE Landing_Page SHALL apply CSS that follows project best practices, with no inline colour values, no inline font-family declarations, and no class definitions that duplicate or override `style.css` class definitions. THE Landing_Page is NOT required to use any specific custom property from `style.css` so long as it satisfies these best-practice constraints.
4. WHEN a visitor clicks the login call-to-action, THE Platform SHALL navigate to the login page. WHEN a visitor clicks the register call-to-action, THE Platform SHALL navigate to the registration page.
5. WHEN an unauthenticated visitor navigates to the root path (`/` or `index.html`), THE Platform SHALL serve the Landing_Page. The current generator page SHALL be moved to a sub-route accessible only to admin sessions.
6. WHEN an authenticated student navigates to the Landing_Page URL, THE Platform SHALL redirect the student to the Student_Dashboard. WHEN an authenticated admin navigates to the Landing_Page URL, THE Platform SHALL redirect the admin to the Admin_Panel.

---

### Requirement 14: Data Persistence Migration

**User Story:** As a platform operator, I want all user data, questions, and results stored in a server-side database, so that data persists across sessions and devices.

#### Acceptance Criteria

1. THE Platform SHALL migrate all persistent data (student profiles, question bank, exam sets, submissions, leaderboard scores) from `localStorage` to the DB.
2. THE DB SHALL use a schema that separates tables or collections for: users, questions, exams, submissions, and leaderboard_scores.
3. WHEN a student logs in from a different browser or device, THE Platform SHALL load that student's Submissions (answers, scores, timestamps) and leaderboard scores from the DB within 5 seconds of successful authentication.
4. IF the DB is unavailable when a student attempts to log in, THEN THE Platform SHALL display an error message and SHALL block access to the Student_Dashboard until connectivity is restored.
5. THE Platform SHALL retain `localStorage` only for active-session UI state (maximum 50 KB per session), such as the current exam configuration during an active attempt. THE Platform SHALL NOT store Session_Tokens in `localStorage`.
6. IF the DB connection is unavailable when a student submits an exam, THEN THE Platform SHALL queue up to 3 Submissions locally, retry the DB write every 30 seconds for a maximum of 10 attempts, and display a status indicator showing the number of pending Submissions and the timestamp of the last retry attempt.
7. IF the retry limit is exhausted without a successful DB write AND at least one Submission has been queued for retry, THEN THE Platform SHALL preserve the queued Submission data locally, display a prompt asking the student to retry manually, and SHALL NOT discard the Submission data. THE Platform SHALL NOT display the manual retry prompt when no Submission has ever been queued for retry.

---

### Requirement 15: UI Preservation

**User Story:** As a developer, I want the upgrade to preserve the existing visual design, so that current users experience no visual regression.

#### Acceptance Criteria

1. THE Platform SHALL retain all CSS custom properties defined in the `:root` block of `style.css` — including colour tokens, spacing tokens, border-radius tokens, shadow tokens, and font-stack tokens — such that no property name is removed and no property value is changed.
2. THE Platform SHALL retain the DOM structure and CSS classes of the existing navbar: `.navbar`, `.nav-brand`, `.brand-icon`, `.nav-links`, `.nav-pill`, `.nav-pill.active`, `.rag-status`, `.status-dot`, `.status-text`, and `.nav-actions`, with no class removed or renamed.
3. THE Platform SHALL retain the CSS classes of the existing reusable components: `.section-card`, `.kpi-tile`, `.chart-card`, `.results-table`, and `.detail-drawer`, with no class removed or renamed.
4. THE Platform SHALL retain the existing multi-layer radial gradient background defined on `.bg-mesh` in `style.css`, with no layer removed and no colour value changed.
5. WHEN new pages (Landing_Page, login/register, Admin_Panel) are added to the Platform, THE Platform SHALL link `style.css` and apply existing component classes. THE build SHALL also verify that all existing pages (`index.html`, `exam.html`, `dashboard.html`, `config.html`) continue to link `style.css`, even when no new pages are added during an upgrade. IF any new or existing page is deployed without a `style.css` link or with CSS rules that override existing `style.css` class definitions, THEN THE Platform SHALL treat this as a build error and SHALL NOT serve that page.
6. THE Platform SHALL NOT remove or rename any CSS class that is present in the baseline snapshot of `style.css`, `index.html`, `exam.html`, `dashboard.html`, or `config.html` taken at the start of the upgrade.
