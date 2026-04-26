// ═══════════════════════════════════════════════════════════════════════════
// EXAM PAGE LOGIC
// ═══════════════════════════════════════════════════════════════════════════
let ES = {
  student: null, setIndex: 0, questions: [], answers: {},
  skipped: new Set(), current: 0, startTime: null, timerRef: null, elapsed: 0
};

// ── Entry Modal ──────────────────────────────────────────────────────────────
const config = Store.get('examConfig');
if (config) {
  document.getElementById('infoSubject').textContent = config.subject || '—';
  document.getElementById('infoDiff').textContent = config.difficulty || '—';
  document.getElementById('infoQCount').textContent = config.sets?.[0]?.length || '—';
}

window.pickSet = i => {
  ES.setIndex = i;
  document.querySelectorAll('.set-sel-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-set="${i}"]`).classList.add('active');
  if (config?.sets?.[i]) {
    document.getElementById('infoQCount').textContent = config.sets[i].length;
  }
};

window.beginExam = () => {
  const name = document.getElementById('studentName').value.trim();
  const roll = document.getElementById('studentRoll').value.trim();
  if (!name) { showToast('⚠️ Please enter your name'); return; }
  if (!roll) { showToast('⚠️ Please enter your roll number'); return; }
  if (!config?.sets) { showToast('⚠️ No exam found. Generate papers first.'); setTimeout(()=>location.href='index.html',2000); return; }

  ES.student = { name, roll };
  ES.questions = config.sets[ES.setIndex];
  ES.startTime = Date.now();

  const L = ['A','B','C','D'];
  document.getElementById('topbarSet').textContent = `Set ${L[ES.setIndex]}`;
  const db = document.getElementById('topbarDiff');
  db.textContent = config.difficulty.charAt(0).toUpperCase() + config.difficulty.slice(1);
  db.className = `exam-badge diff-badge ${config.difficulty}`;
  document.getElementById('topbarSubject').textContent = config.subject || 'Exam';

  document.getElementById('entryOverlay').style.display = 'none';
  document.getElementById('examLayout').style.display = 'grid';

  document.getElementById('sidebarStudentInfo').innerHTML = `
    <div style="font-weight:700;font-size:0.88rem;margin-bottom:2px">${name}</div>
    <div style="color:var(--muted);font-size:0.75rem">${roll} · Set ${L[ES.setIndex]}</div>`;
  document.getElementById('totalCount').textContent = ES.questions.length;

  buildQGrid();
  renderQ(0);
  startTimer();
};

function startTimer() {
  ES.timerRef = setInterval(() => {
    ES.elapsed = Math.floor((Date.now() - ES.startTime) / 1000);
    const m = String(Math.floor(ES.elapsed/60)).padStart(2,'0');
    const s = String(ES.elapsed%60).padStart(2,'0');
    document.getElementById('timerDisplay').textContent = `${m}:${s}`;
  }, 1000);
}

function buildQGrid() {
  document.getElementById('qGrid').innerHTML = ES.questions.map((_,i) =>
    `<button class="q-grid-btn ${i===0?'current':''}" id="qgb${i}" onclick="jumpTo(${i})">${i+1}</button>`
  ).join('');
}

function updateQGrid() {
  ES.questions.forEach((_,i) => {
    const b = document.getElementById(`qgb${i}`);
    if (!b) return;
    b.className = 'q-grid-btn';
    if (i === ES.current) b.classList.add('current');
    else if (ES.answers[i] !== undefined) b.classList.add('answered');
    else if (ES.skipped.has(i)) b.classList.add('skipped');
  });
  const answered = Object.keys(ES.answers).length;
  document.getElementById('answeredCount').textContent = answered;
  document.getElementById('sidebarProgFill').style.width = (answered/ES.questions.length*100)+'%';
  document.getElementById('examTopProgFill').style.width = ((ES.current+1)/ES.questions.length*100)+'%';
}

function renderQ(idx) {
  ES.current = idx;
  const q = ES.questions[idx];
  const total = ES.questions.length;

  document.getElementById('qNumBadge').textContent = `Q ${idx+1}`;
  document.getElementById('qTypeChip').textContent = q.type;
  document.getElementById('qTopicChip').textContent = q.topic || 'General';
  document.getElementById('qMarksChip').textContent = getMarks(q.type);
  document.getElementById('qBody').textContent = q.q;
  document.getElementById('qPosition').textContent = `${idx+1} of ${total}`;
  document.getElementById('prevBtn').disabled = idx === 0;
  document.getElementById('nextBtn').textContent = idx === total-1 ? 'Finish' : 'Next';

  renderAnswerArea(q, idx);
  updateQGrid();
}

function renderAnswerArea(q, idx) {
  const area = document.getElementById('qAnswerArea');
  const saved = ES.answers[idx];

  if (q.type === 'MCQ') {
    area.innerHTML = `<div class="mcq-options">${q.opts.map((o,i)=>`
      <button class="mcq-opt ${saved===i?'selected':''}" onclick="selectMCQ(${idx},${i})">
        <span class="opt-letter">${['A','B','C','D'][i]}</span>${o}
      </button>`).join('')}</div>`;
  } else if (q.type === 'True/False') {
    area.innerHTML = `<div class="tf-row">
      <button class="tf-opt ${saved===true?'selected':''}" onclick="selectTF(${idx},true)">✅ True</button>
      <button class="tf-opt ${saved===false?'selected':''}" onclick="selectTF(${idx},false)">❌ False</button>
    </div>`;
  } else if (q.type === 'Fill in the Blank') {
    area.innerHTML = `<input class="fill-input" placeholder="Type your answer..." value="${saved||''}" oninput="saveText(${idx},this.value)"/>`;
  } else {
    area.innerHTML = `<textarea class="text-answer-area" placeholder="Write your answer here..." oninput="saveText(${idx},this.value)">${saved||''}</textarea>`;
  }
}

window.selectMCQ = (qi, oi) => { ES.answers[qi] = oi; renderAnswerArea(ES.questions[qi], qi); updateQGrid(); };
window.selectTF = (qi, v) => { ES.answers[qi] = v; renderAnswerArea(ES.questions[qi], qi); updateQGrid(); };
window.saveText = (qi, v) => { if (v.trim()) ES.answers[qi] = v.trim(); else delete ES.answers[qi]; updateQGrid(); };
window.jumpTo = i => renderQ(i);
window.navigate = dir => { const n = ES.current + dir; if (n >= 0 && n < ES.questions.length) renderQ(n); };
window.skipQuestion = () => { ES.skipped.add(ES.current); updateQGrid(); if (ES.current < ES.questions.length-1) renderQ(ES.current+1); };

window.confirmSubmit = () => {
  const answered = Object.keys(ES.answers).length;
  const total = ES.questions.length;
  document.getElementById('submitSummary').innerHTML = `
    <div style="display:flex;flex-direction:column;gap:8px">
      <div style="display:flex;justify-content:space-between"><span>Answered:</span><span style="color:var(--green-l);font-weight:700">${answered}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Unanswered:</span><span style="color:var(--red-l);font-weight:700">${total-answered}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Skipped:</span><span style="color:var(--yellow-l);font-weight:700">${ES.skipped.size}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Total:</span><span style="font-weight:700">${total}</span></div>
    </div>`;
  document.getElementById('submitOverlay').style.display = 'flex';
};
window.closeSubmitModal = () => { document.getElementById('submitOverlay').style.display = 'none'; };

window.submitPaper = async () => {
  clearInterval(ES.timerRef);
  document.getElementById('submitOverlay').style.display = 'none';
  document.getElementById('analyzingOverlay').style.display = 'flex';

  const analyzeSteps = ['Processing answers...','Matching with RAG knowledge base...','Evaluating topic coverage...','Generating performance insights...','Finalizing analysis...'];
  for (let i = 0; i < analyzeSteps.length; i++) {
    await delay(500);
    document.getElementById('analyzeBarFill').style.width = ((i+1)/analyzeSteps.length*100)+'%';
    document.getElementById('analyzeLabel').textContent = analyzeSteps[i];
  }

  let result;
  try {
    const ragResult = await RAG.analyze({ questions: ES.questions, answers: ES.answers, student: ES.student });
    result = ragResult;
  } catch {
    result = localAnalyze(ES.questions, ES.answers);
  }

  const submission = {
    id: Date.now(), student: ES.student, setIndex: ES.setIndex,
    difficulty: config.difficulty, subject: config.subject,
    timeTaken: ES.elapsed, answers: ES.answers, result,
    submittedAt: new Date().toISOString()
  };

  const subs = Store.get('submissions') || [];
  subs.push(submission);
  Store.set('submissions', subs);

  window.location.href = 'dashboard.html';
};
