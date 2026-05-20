// ═══════════════════════════════════════════════════════════════════════════
// EXAM PAGE LOGIC — Server-Driven (Task 14.3)
// ═══════════════════════════════════════════════════════════════════════════
// Data source: /api/student/exams/{exam_set_id} (DB-backed)
// Timer: 60-minute countdown with auto-submit at zero
// Submission: POST /api/student/submit with idempotency key
// Already-completed detection: GET /api/student/exams/{exam_set_id}/status
// ═══════════════════════════════════════════════════════════════════════════

let ES = {
  student: null, setLabel: '', examSetId: null, subject: '',
  questions: [], answers: {}, skipped: new Set(), current: 0,
  startTime: null, timerRef: null, elapsed: 0,
  totalSeconds: 60 * 60, // 60 minutes
  idempotencyKey: null
};

// ── Utility: Generate UUID v4 ────────────────────────────────────────────────
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

// ── Utility: Get URL parameter ───────────────────────────────────────────────
function getUrlParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

// ── Exam Selection UI (when no ?set= param) ─────────────────────────────────
async function renderExamSelection() {
  // Hide exam-specific elements
  document.getElementById('entryOverlay').style.display = 'none';
  document.getElementById('examLayout').style.display = 'none';
  const topbar = document.getElementById('examTopbar');
  if (topbar) topbar.style.display = 'none';

  // Create selection container
  const body = document.querySelector('.exam-body');
  const selectionDiv = document.createElement('div');
  selectionDiv.className = 'exam-selection-view';
  selectionDiv.style.cssText = 'max-width:900px;margin:100px auto 40px;padding:0 20px;position:relative;z-index:1;';
  selectionDiv.innerHTML = '<div style="text-align:center;padding:40px;color:var(--muted);">Loading available exams...</div>';
  body.appendChild(selectionDiv);

  try {
    const res = await fetch('/api/student/exams', { credentials: 'include' });

    if (res.status === 401) {
      window.location.href = '/login';
      return;
    }

    if (!res.ok) {
      selectionDiv.innerHTML = '<div style="text-align:center;padding:40px;color:var(--red-l);">Failed to load exams. Please try again.</div>';
      return;
    }

    const data = await res.json();
    const subjects = data.subjects || [];

    if (subjects.length === 0) {
      selectionDiv.innerHTML = `
        <div style="text-align:center;padding:60px 20px;">
          <div style="font-size:3rem;margin-bottom:16px;">📋</div>
          <h2 style="font-size:1.5rem;font-weight:700;margin-bottom:8px;">No Exams Available</h2>
          <p style="color:var(--muted);margin-bottom:24px;">There are no published exams at the moment. Check back later.</p>
          <a href="/dashboard" class="btn-generate" style="text-decoration:none;display:inline-flex;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;"><path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3"/></svg>
            Back to Dashboard
          </a>
        </div>`;
      return;
    }

    // Render subject cards with exam sets
    let html = `
      <div style="text-align:center;margin-bottom:32px;">
        <h2 style="font-size:1.6rem;font-weight:700;margin-bottom:8px;">Available Exams</h2>
        <p style="color:var(--muted);font-size:0.9rem;">Select an exam set to begin your test</p>
      </div>
      <div style="display:flex;flex-direction:column;gap:20px;">`;

    subjects.forEach(function(subjectGroup) {
      html += `
        <div class="section-card" style="border:1px solid var(--border);border-radius:var(--r);overflow:hidden;">
          <div style="padding:20px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;">
            <div style="width:40px;height:40px;border-radius:10px;background:linear-gradient(135deg,rgba(124,58,237,0.2),rgba(37,99,235,0.2));display:flex;align-items:center;justify-content:center;font-size:1.2rem;">📚</div>
            <div>
              <h3 style="font-size:1.1rem;font-weight:700;margin:0;">${escapeHtmlExam(subjectGroup.subject)}</h3>
              <p style="color:var(--muted);font-size:0.8rem;margin:0;">${subjectGroup.available_exams} exam${subjectGroup.available_exams !== 1 ? 's' : ''} available</p>
            </div>
          </div>
          <div style="padding:16px 24px;display:flex;flex-direction:column;gap:12px;">`;

      subjectGroup.exams.forEach(function(exam) {
        const examName = exam.exam_name || 'Untitled Exam';
        const createdDate = exam.created_at
          ? new Date(exam.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
          : '';
        const sets = exam.sets || [];

        html += `
          <div style="padding:14px 16px;background:var(--s2);border:1px solid var(--border);border-radius:var(--rs);">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
              <div>
                <span style="font-weight:600;font-size:0.92rem;">${escapeHtmlExam(examName)}</span>
                <span style="color:var(--muted);font-size:0.78rem;margin-left:8px;">${createdDate}</span>
              </div>
              <span style="font-size:0.75rem;color:var(--muted);">${exam.set_count} sets</span>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">`;

        if (sets.length > 0) {
          sets.forEach(function(s) {
            html += `<a href="/exam?set=${s.exam_set_id}" class="btn-outline small" style="text-decoration:none;padding:6px 14px;font-size:0.82rem;font-weight:600;">Set ${escapeHtmlExam(s.set_label)}</a>`;
          });
        } else {
          // Fallback if sets not provided
          html += `<span style="color:var(--muted);font-size:0.8rem;">No sets available</span>`;
        }

        html += `
            </div>
          </div>`;
      });

      html += `
          </div>
        </div>`;
    });

    html += '</div>';
    selectionDiv.innerHTML = html;

  } catch (e) {
    console.error('Failed to load exam selection:', e);
    selectionDiv.innerHTML = '<div style="text-align:center;padding:40px;color:var(--red-l);">Network error loading exams. Please try again.</div>';
  }
}

function escapeHtmlExam(str) {
  var div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

// ── Initialize exam page ─────────────────────────────────────────────────────
(async function initExamPage() {
  const examSetId = getUrlParam('set');
  if (!examSetId) {
    // No set specified — show exam selection UI
    await renderExamSelection();
    return;
  }

  ES.examSetId = examSetId;
  ES.idempotencyKey = generateUUID();

  // Check if this exam set has already been completed (REQ-9.7)
  try {
    const statusRes = await fetch(`/api/student/exams/${examSetId}/status`, {
      credentials: 'include'
    });

    if (statusRes.status === 401) {
      window.location.href = '/login';
      return;
    }

    if (statusRes.ok) {
      const statusData = await statusRes.json();
      if (statusData.completed) {
        renderPreviousResult(statusData.submission);
        return;
      }
    }
  } catch (e) {
    console.warn('Status check failed, proceeding with exam:', e);
  }

  // Load exam questions from the server (REQ-9.1)
  try {
    const examRes = await fetch(`/api/student/exams/${examSetId}`, {
      credentials: 'include'
    });

    if (examRes.status === 401) {
      window.location.href = '/login';
      return;
    }

    if (examRes.status === 404) {
      showToast('⚠️ Exam not found or not available.');
      setTimeout(() => { window.location.href = '/dashboard'; }, 2000);
      return;
    }

    if (!examRes.ok) {
      showToast('⚠️ Failed to load exam. Please try again.');
      setTimeout(() => { window.location.href = '/dashboard'; }, 2000);
      return;
    }

    const examData = await examRes.json();
    ES.questions = examData.questions;
    ES.setLabel = examData.set_label || 'A';
    ES.subject = examData.subject || 'Exam';

    // Populate topbar info
    document.getElementById('topbarSet').textContent = `Set ${ES.setLabel}`;
    document.getElementById('topbarDiff').textContent = examData.difficulty
      ? examData.difficulty.charAt(0).toUpperCase() + examData.difficulty.slice(1)
      : 'Medium';
    document.getElementById('topbarSubject').textContent = ES.subject;

    // Update exam info box in entry modal
    document.getElementById('infoSubject').textContent = ES.subject;
    document.getElementById('infoDiff').textContent = examData.difficulty || 'Medium';
    document.getElementById('infoQCount').textContent = ES.questions.length;

  } catch (e) {
    console.error('Failed to load exam:', e);
    showToast('⚠️ Network error loading exam. Please try again.');
    setTimeout(() => { window.location.href = '/dashboard'; }, 2000);
    return;
  }

  // Show the entry overlay for student to confirm start
  document.getElementById('entryOverlay').style.display = 'flex';
})();

// ── Render previous result view (REQ-9.7) ────────────────────────────────────
function renderPreviousResult(submission) {
  // Hide entry overlay and exam layout
  document.getElementById('entryOverlay').style.display = 'none';
  document.getElementById('examLayout').style.display = 'none';

  // Create a previous-result view
  const body = document.querySelector('.exam-body');
  const resultDiv = document.createElement('div');
  resultDiv.className = 'previous-result-view';
  resultDiv.style.cssText = 'display:flex;align-items:center;justify-content:center;min-height:100vh;padding:2rem;';

  const scorePct = submission.score_pct != null ? Math.round(submission.score_pct) : '—';
  const passFlag = submission.pass_flag ? '✅ Passed' : '❌ Failed';
  const submittedAt = submission.submitted_at
    ? new Date(submission.submitted_at).toLocaleString()
    : '—';
  const timeTaken = submission.time_taken_sec != null
    ? `${Math.floor(submission.time_taken_sec / 60)}m ${submission.time_taken_sec % 60}s`
    : '—';

  resultDiv.innerHTML = `
    <div class="entry-modal" style="max-width:500px;text-align:center;">
      <div class="entry-icon">📋</div>
      <h2>Already Completed</h2>
      <p style="color:var(--muted);margin-bottom:1.5rem;">You have already completed this exam set.</p>
      <div style="display:flex;flex-direction:column;gap:12px;margin-bottom:1.5rem;text-align:left;">
        <div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--card-bg);border-radius:8px;">
          <span>Score:</span><span style="font-weight:700;color:var(--green-l);">${scorePct}%</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--card-bg);border-radius:8px;">
          <span>Status:</span><span style="font-weight:700;">${passFlag}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--card-bg);border-radius:8px;">
          <span>Time Taken:</span><span>${timeTaken}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--card-bg);border-radius:8px;">
          <span>Submitted:</span><span>${submittedAt}</span>
        </div>
      </div>
      <div style="display:flex;gap:12px;justify-content:center;">
        <a href="/dashboard" class="btn-generate" style="text-decoration:none;">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3"/></svg>
          Go to Dashboard
        </a>
      </div>
    </div>`;

  body.appendChild(resultDiv);
}

// ── Entry Modal — hide set selector since set comes from URL ─────────────────
(function hideSetSelector() {
  const setSelector = document.querySelector('.set-selector');
  if (setSelector) setSelector.style.display = 'none';
  // Update the info box to show 60-minute time limit
  const timeRow = document.querySelector('.exam-info-box .info-row:last-child span:first-child');
  if (timeRow) timeRow.textContent = '⏱ Time Limit: 60 minutes';
})();

window.pickSet = () => {}; // No-op since set is URL-driven

window.beginExam = () => {
  const name = document.getElementById('studentName').value.trim();
  const roll = document.getElementById('studentRoll').value.trim();
  if (!name) { showToast('⚠️ Please enter your name'); return; }
  if (!roll) { showToast('⚠️ Please enter your roll number'); return; }
  if (!ES.questions || ES.questions.length === 0) {
    showToast('⚠️ No exam loaded. Please try again.');
    setTimeout(() => { window.location.href = '/dashboard'; }, 2000);
    return;
  }

  ES.student = { name, roll };
  ES.startTime = Date.now();

  document.getElementById('entryOverlay').style.display = 'none';
  document.getElementById('examLayout').style.display = 'grid';

  document.getElementById('sidebarStudentInfo').innerHTML = `
    <div style="font-weight:700;font-size:0.88rem;margin-bottom:2px">${name}</div>
    <div style="color:var(--muted);font-size:0.75rem">${roll} · Set ${ES.setLabel}</div>`;
  document.getElementById('totalCount').textContent = ES.questions.length;

  buildQGrid();
  renderQ(0);
  startCountdown();
};

// ── 60-Minute Countdown Timer (REQ-9.6) ──────────────────────────────────────
function startCountdown() {
  ES.totalSeconds = 60 * 60; // 60 minutes
  updateTimerDisplay();

  ES.timerRef = setInterval(() => {
    ES.elapsed = Math.floor((Date.now() - ES.startTime) / 1000);
    const remaining = (60 * 60) - ES.elapsed;

    if (remaining <= 0) {
      // Auto-submit when timer reaches zero (REQ-9.6)
      clearInterval(ES.timerRef);
      document.getElementById('timerDisplay').textContent = '00:00';
      showToast('⏰ Time is up! Auto-submitting your answers...');
      submitPaper();
      return;
    }

    const m = String(Math.floor(remaining / 60)).padStart(2, '0');
    const s = String(remaining % 60).padStart(2, '0');
    document.getElementById('timerDisplay').textContent = `${m}:${s}`;
  }, 1000);
}

function updateTimerDisplay() {
  document.getElementById('timerDisplay').textContent = '60:00';
}

// ── Question Grid ────────────────────────────────────────────────────────────
function buildQGrid() {
  document.getElementById('qGrid').innerHTML = ES.questions.map((_, i) =>
    `<button class="q-grid-btn ${i === 0 ? 'current' : ''}" id="qgb${i}" onclick="jumpTo(${i})">${i + 1}</button>`
  ).join('');
}

function updateQGrid() {
  ES.questions.forEach((_, i) => {
    const b = document.getElementById(`qgb${i}`);
    if (!b) return;
    b.className = 'q-grid-btn';
    if (i === ES.current) b.classList.add('current');
    else if (ES.answers[i] !== undefined) b.classList.add('answered');
    else if (ES.skipped.has(i)) b.classList.add('skipped');
  });
  const answered = Object.keys(ES.answers).length;
  document.getElementById('answeredCount').textContent = answered;
  document.getElementById('sidebarProgFill').style.width = (answered / ES.questions.length * 100) + '%';
  document.getElementById('examTopProgFill').style.width = ((ES.current + 1) / ES.questions.length * 100) + '%';
}

// ── Question Rendering ───────────────────────────────────────────────────────
function renderQ(idx) {
  ES.current = idx;
  const q = ES.questions[idx];
  const total = ES.questions.length;

  document.getElementById('qNumBadge').textContent = `Q ${idx + 1}`;
  document.getElementById('qTypeChip').textContent = q.type || 'MCQ';
  document.getElementById('qTopicChip').textContent = q.topic || 'General';
  document.getElementById('qMarksChip').textContent = getMarks(q.type || 'MCQ');
  document.getElementById('qBody').textContent = q.q;
  document.getElementById('qPosition').textContent = `${idx + 1} of ${total}`;
  document.getElementById('prevBtn').disabled = idx === 0;
  document.getElementById('nextBtn').textContent = idx === total - 1 ? 'Finish' : 'Next';

  renderAnswerArea(q, idx);
  updateQGrid();
}

function renderAnswerArea(q, idx) {
  const area = document.getElementById('qAnswerArea');
  const saved = ES.answers[idx];
  const type = q.type || 'MCQ';

  if (type === 'MCQ') {
    area.innerHTML = `<div class="mcq-options">${q.opts.map((o, i) => `
      <button class="mcq-opt ${saved === i ? 'selected' : ''}" onclick="selectMCQ(${idx},${i})">
        <span class="opt-letter">${['A', 'B', 'C', 'D'][i]}</span>${o}
      </button>`).join('')}</div>`;
  } else if (type === 'True/False') {
    area.innerHTML = `<div class="tf-row">
      <button class="tf-opt ${saved === true ? 'selected' : ''}" onclick="selectTF(${idx},true)">✅ True</button>
      <button class="tf-opt ${saved === false ? 'selected' : ''}" onclick="selectTF(${idx},false)">❌ False</button>
    </div>`;
  } else if (type === 'Fill in the Blank') {
    area.innerHTML = `<input class="fill-input" placeholder="Type your answer..." value="${saved || ''}" oninput="saveText(${idx},this.value)"/>`;
  } else {
    area.innerHTML = `<textarea class="text-answer-area" placeholder="Write your answer here..." oninput="saveText(${idx},this.value)">${saved || ''}</textarea>`;
  }
}

// ── Answer Selection ─────────────────────────────────────────────────────────
window.selectMCQ = (qi, oi) => { ES.answers[qi] = oi; renderAnswerArea(ES.questions[qi], qi); updateQGrid(); };
window.selectTF = (qi, v) => { ES.answers[qi] = v; renderAnswerArea(ES.questions[qi], qi); updateQGrid(); };
window.saveText = (qi, v) => { if (v.trim()) ES.answers[qi] = v.trim(); else delete ES.answers[qi]; updateQGrid(); };
window.jumpTo = i => renderQ(i);
window.navigate = dir => { const n = ES.current + dir; if (n >= 0 && n < ES.questions.length) renderQ(n); };
window.skipQuestion = () => { ES.skipped.add(ES.current); updateQGrid(); if (ES.current < ES.questions.length - 1) renderQ(ES.current + 1); };

// ── Submit Confirmation Modal ────────────────────────────────────────────────
window.confirmSubmit = () => {
  const answered = Object.keys(ES.answers).length;
  const total = ES.questions.length;
  document.getElementById('submitSummary').innerHTML = `
    <div style="display:flex;flex-direction:column;gap:8px">
      <div style="display:flex;justify-content:space-between"><span>Answered:</span><span style="color:var(--green-l);font-weight:700">${answered}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Unanswered:</span><span style="color:var(--red-l);font-weight:700">${total - answered}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Skipped:</span><span style="color:var(--yellow-l);font-weight:700">${ES.skipped.size}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Total:</span><span style="font-weight:700">${total}</span></div>
    </div>`;
  document.getElementById('submitOverlay').style.display = 'flex';
};
window.closeSubmitModal = () => { document.getElementById('submitOverlay').style.display = 'none'; };

// ═══════════════════════════════════════════════════════════════════════════
// SUBMISSION QUEUE — Offline Queue with Retry (REQ-9.4, 9.5, 14.5, 14.6, 14.7)
// ═══════════════════════════════════════════════════════════════════════════
// Queue up to 3 submissions in localStorage under key `ef_submission_queue`.
// Retry every 30 seconds, max 10 attempts per submission.
// Show status indicator with pending count and last-retry timestamp.
// Show manual retry prompt when retries exhausted AND attempts >= 1.
// ═══════════════════════════════════════════════════════════════════════════

var SubmissionQueue = (function() {
  'use strict';

  const STORAGE_KEY = 'ef_submission_queue';
  const MAX_QUEUE_SIZE = 3;
  const MAX_ATTEMPTS = 10;
  const RETRY_INTERVAL_MS = 30 * 1000; // 30 seconds

  let retryTimerRef = null;

  // ── Queue persistence helpers ──────────────────────────────────────────────

  function getQueue() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function saveQueue(queue) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
    } catch (e) {
      console.error('Failed to save submission queue:', e);
    }
  }

  // ── Queue operations ───────────────────────────────────────────────────────

  function enqueue(payload) {
    const queue = getQueue();
    if (queue.length >= MAX_QUEUE_SIZE) {
      console.warn('Submission queue full (max ' + MAX_QUEUE_SIZE + '). Cannot queue more.');
      return false;
    }

    const entry = {
      id: generateUUID(),
      exam_set_id: payload.exam_set_id,
      answers: payload.answers,
      time_taken_sec: payload.time_taken_sec,
      idempotency_key: payload.idempotency_key,
      queued_at: new Date().toISOString(),
      attempts: 0,
      last_attempt_at: null
    };

    queue.push(entry);
    saveQueue(queue);
    updateStatusIndicator();
    startRetryLoop();
    return true;
  }

  function removeEntry(entryId) {
    const queue = getQueue();
    const filtered = queue.filter(function(e) { return e.id !== entryId; });
    saveQueue(filtered);
    updateStatusIndicator();
  }

  // ── Retry logic ────────────────────────────────────────────────────────────

  async function retrySubmission(entry) {
    try {
      const res = await fetch('/api/student/submit', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          exam_set_id: entry.exam_set_id,
          answers: entry.answers,
          time_taken_sec: entry.time_taken_sec,
          idempotency_key: entry.idempotency_key
        })
      });

      if (res.status === 401) {
        // Session expired — can't retry without auth
        showToast('⚠️ Session expired. Please log in to retry submissions.');
        return false;
      }

      if (res.ok) {
        return true; // Success
      }

      // 5xx or other server error — not successful
      if (res.status >= 500) {
        return false;
      }

      // 4xx (other than 401) — likely a client error, don't keep retrying
      // But for safety, treat as failure and let retry logic handle it
      return false;
    } catch (e) {
      // Network error — DB/server unavailable
      return false;
    }
  }

  async function processQueue() {
    const queue = getQueue();
    if (queue.length === 0) {
      stopRetryLoop();
      updateStatusIndicator();
      return;
    }

    let anySuccess = false;

    for (let i = 0; i < queue.length; i++) {
      const entry = queue[i];

      // Skip entries that have exhausted retries
      if (entry.attempts >= MAX_ATTEMPTS) {
        continue;
      }

      // Attempt retry
      entry.attempts += 1;
      entry.last_attempt_at = new Date().toISOString();

      const success = await retrySubmission(entry);

      if (success) {
        // Remove from queue and redirect
        queue.splice(i, 1);
        i--; // Adjust index after removal
        saveQueue(queue);
        anySuccess = true;
        showToast('✅ Submission saved successfully!');
      } else {
        // Update the entry with new attempt count
        saveQueue(queue);
      }
    }

    updateStatusIndicator();

    // If any submission succeeded and queue is now empty, redirect to dashboard
    if (anySuccess && getQueue().length === 0) {
      stopRetryLoop();
      window.location.href = '/dashboard';
      return;
    }

    // If any submission succeeded but there are still items, redirect anyway
    // (REQ-9.5: redirect after successful persistence)
    if (anySuccess) {
      stopRetryLoop();
      window.location.href = '/dashboard';
      return;
    }

    // Check if any entries have exhausted retries
    checkExhaustedRetries();
  }

  function checkExhaustedRetries() {
    const queue = getQueue();
    const exhausted = queue.filter(function(e) {
      return e.attempts >= MAX_ATTEMPTS && e.attempts >= 1;
    });

    if (exhausted.length > 0) {
      // All retries exhausted for at least one entry — show manual prompt
      stopRetryLoop();
      showManualRetryPrompt(exhausted);
    }
  }

  // ── Retry loop management ─────────────────────────────────────────────────

  function startRetryLoop() {
    if (retryTimerRef) return; // Already running
    retryTimerRef = setInterval(function() {
      processQueue();
    }, RETRY_INTERVAL_MS);
  }

  function stopRetryLoop() {
    if (retryTimerRef) {
      clearInterval(retryTimerRef);
      retryTimerRef = null;
    }
  }

  // ── UI: Status indicator ───────────────────────────────────────────────────

  function updateStatusIndicator() {
    const statusEl = document.getElementById('submission-queue-status');
    if (!statusEl) return;

    const queue = getQueue();

    if (queue.length === 0) {
      statusEl.style.display = 'none';
      return;
    }

    statusEl.style.display = 'flex';

    const pendingEl = document.getElementById('queue-pending-count');
    const lastRetryEl = document.getElementById('queue-last-retry');

    if (pendingEl) {
      pendingEl.textContent = queue.length + ' pending';
    }

    if (lastRetryEl) {
      // Find the most recent last_attempt_at across all entries
      let lastAttempt = null;
      for (let i = 0; i < queue.length; i++) {
        if (queue[i].last_attempt_at) {
          const ts = new Date(queue[i].last_attempt_at);
          if (!lastAttempt || ts > lastAttempt) {
            lastAttempt = ts;
          }
        }
      }

      if (lastAttempt) {
        lastRetryEl.textContent = 'Last retry: ' + lastAttempt.toLocaleTimeString();
      } else {
        lastRetryEl.textContent = 'Last retry: —';
      }
    }
  }

  // ── UI: Manual retry prompt (REQ-14.7) ─────────────────────────────────────

  function showManualRetryPrompt(exhaustedEntries) {
    const promptEl = document.getElementById('manual-retry-prompt');
    if (!promptEl) return;

    // Only show when queue is not empty AND at least one attempt has been made
    const queue = getQueue();
    if (queue.length === 0) return;

    const hasAttempted = queue.some(function(e) { return e.attempts >= 1; });
    if (!hasAttempted) return;

    // Populate details
    const detailsEl = document.getElementById('manual-retry-details');
    if (detailsEl) {
      detailsEl.innerHTML = exhaustedEntries.map(function(entry) {
        return '<div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--card-bg);border-radius:8px;">' +
          '<span>Queued:</span><span>' + new Date(entry.queued_at).toLocaleString() + '</span>' +
          '</div>' +
          '<div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--card-bg);border-radius:8px;">' +
          '<span>Attempts:</span><span style="color:var(--red-l);font-weight:700;">' + entry.attempts + '/' + MAX_ATTEMPTS + '</span>' +
          '</div>';
      }).join('');
    }

    promptEl.style.display = 'flex';
  }

  function hideManualRetryPrompt() {
    const promptEl = document.getElementById('manual-retry-prompt');
    if (promptEl) {
      promptEl.style.display = 'none';
    }
  }

  // ── Public: Manual retry action ────────────────────────────────────────────

  function manualRetry() {
    hideManualRetryPrompt();

    // Reset attempts for all entries so they can be retried
    const queue = getQueue();
    for (let i = 0; i < queue.length; i++) {
      queue[i].attempts = 0;
      queue[i].last_attempt_at = null;
    }
    saveQueue(queue);
    updateStatusIndicator();

    // Immediately try once, then start the loop
    processQueue();
    startRetryLoop();
    showToast('🔄 Retrying submissions...');
  }

  function dismissPrompt() {
    hideManualRetryPrompt();
  }

  // ── Initialization: check for pending queue on page load ───────────────────

  function init() {
    const queue = getQueue();
    if (queue.length > 0) {
      updateStatusIndicator();

      // Check if any entries have exhausted retries already
      const exhausted = queue.filter(function(e) {
        return e.attempts >= MAX_ATTEMPTS && e.attempts >= 1;
      });

      if (exhausted.length > 0) {
        showManualRetryPrompt(exhausted);
      } else {
        // Resume retry loop for pending entries
        startRetryLoop();
      }
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  return {
    getQueue: getQueue,
    enqueue: enqueue,
    removeEntry: removeEntry,
    processQueue: processQueue,
    manualRetry: manualRetry,
    dismissPrompt: dismissPrompt,
    updateStatusIndicator: updateStatusIndicator,
    startRetryLoop: startRetryLoop,
    stopRetryLoop: stopRetryLoop,
    init: init,
    MAX_QUEUE_SIZE: MAX_QUEUE_SIZE,
    MAX_ATTEMPTS: MAX_ATTEMPTS,
    RETRY_INTERVAL_MS: RETRY_INTERVAL_MS,
    STORAGE_KEY: STORAGE_KEY
  };
})();

// Initialize the submission queue on page load
SubmissionQueue.init();

// ── Submit Paper (POST /api/student/submit) ──────────────────────────────────
window.submitPaper = async () => {
  clearInterval(ES.timerRef);
  document.getElementById('submitOverlay').style.display = 'none';
  document.getElementById('analyzingOverlay').style.display = 'flex';

  const analyzeSteps = [
    'Processing answers...',
    'Scoring your responses...',
    'Computing topic breakdown...',
    'Generating performance insights...',
    'Finalizing submission...'
  ];
  for (let i = 0; i < analyzeSteps.length; i++) {
    await delay(400);
    document.getElementById('analyzeBarFill').style.width = ((i + 1) / analyzeSteps.length * 100) + '%';
    document.getElementById('analyzeLabel').textContent = analyzeSteps[i];
  }

  // Build the answers map with string keys matching question indices
  const answersMap = {};
  for (const [key, value] of Object.entries(ES.answers)) {
    // Convert MCQ numeric index to letter (A, B, C, D) for the backend
    if (typeof value === 'number') {
      answersMap[String(key)] = ['A', 'B', 'C', 'D'][value] || String(value);
    } else {
      answersMap[String(key)] = String(value);
    }
  }

  const timeTakenSec = Math.floor((Date.now() - ES.startTime) / 1000);

  const payload = {
    exam_set_id: ES.examSetId,
    answers: answersMap,
    time_taken_sec: timeTakenSec,
    idempotency_key: ES.idempotencyKey
  };

  try {
    const res = await fetch('/api/student/submit', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.status === 401) {
      showToast('⚠️ Session expired. Please log in again.');
      setTimeout(() => { window.location.href = '/login'; }, 2000);
      return;
    }

    if (res.status >= 500) {
      // Server error (5xx) — stay on exam page with retry UI (REQ-9.4)
      throw { serverError: true, status: res.status };
    }

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.message || `Client error: ${res.status}`);
    }

    // Success — redirect to dashboard (REQ-9.5)
    window.location.href = '/dashboard';

  } catch (e) {
    console.error('Submission failed:', e);
    document.getElementById('analyzingOverlay').style.display = 'none';

    if (e && e.serverError) {
      // 5xx error — queue the submission for retry (REQ-14.6)
      const queued = SubmissionQueue.enqueue(payload);
      if (queued) {
        showToast('⚠️ Server unavailable. Submission queued for automatic retry.');
      } else {
        showToast('❌ Submission queue is full. Please try again later.');
      }
    } else {
      showToast(`❌ Submission failed: ${e.message || 'Unknown error'}. Please try again.`);
    }

    // Re-show the exam so the student can see the retry status
    document.getElementById('examLayout').style.display = 'grid';
    // Restart the timer with remaining time
    startCountdown();
  }
};
