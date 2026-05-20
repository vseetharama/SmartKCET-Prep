// ═══════════════════════════════════════════════════════════════════════════
// STUDENT DASHBOARD PAGE LOGIC — Personal Analytics
// Fetches data from /api/student/submissions and /api/student/leaderboard/me
// ═══════════════════════════════════════════════════════════════════════════
let charts = {};
let allSubmissions = [];
let filteredSubs = [];
let leaderboardData = null;
let sortKey = 'submitted_at';
let sortDir = -1;

const CHART_DEFAULTS = {
  color: '#e8e8f4',
  grid: 'rgba(255,255,255,0.05)',
  muted: '#6868a0',
  font: { family: "'Segoe UI', system-ui, sans-serif", size: 11 }
};

Chart.defaults.color = CHART_DEFAULTS.color;
Chart.defaults.font.family = CHART_DEFAULTS.font.family;
Chart.defaults.font.size = CHART_DEFAULTS.font.size;

// ── Init ─────────────────────────────────────────────────────────────────────
async function initDashboard() {
  document.getElementById('lastUpdated').textContent = `Last updated: ${new Date().toLocaleTimeString()}`;

  // Hide the student filter (admin-only)
  const studentFilter = document.getElementById('filterStudent');
  if (studentFilter) {
    studentFilter.closest('.filter-group').style.display = 'none';
  }

  try {
    // Fetch submissions from API
    const subRes = await fetch('/api/student/submissions', { credentials: 'include' });
    if (!subRes.ok) {
      if (subRes.status === 401) {
        window.location.href = '/login';
        return;
      }
      throw new Error(`Failed to fetch submissions: HTTP ${subRes.status}`);
    }
    const subData = await subRes.json();
    allSubmissions = subData.submissions || [];

    // Fetch leaderboard data
    try {
      const lbRes = await fetch('/api/student/leaderboard/me', { credentials: 'include' });
      if (lbRes.ok) {
        leaderboardData = await lbRes.json();
      }
    } catch (e) {
      console.warn('Leaderboard data unavailable:', e.message);
      leaderboardData = null;
    }
  } catch (e) {
    console.error('Dashboard init error:', e);
    document.getElementById('emptyState').style.display = 'block';
    document.getElementById('dashContent').style.display = 'none';
    return;
  }

  if (allSubmissions.length === 0) {
    document.getElementById('emptyState').style.display = 'block';
    document.getElementById('dashContent').style.display = 'none';
    return;
  }

  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('dashContent').style.display = 'block';

  populateSubjectFilter();
  applyFilters();

  // Migrate any pre-existing localStorage submission data (REQ-14.1, REQ-14.4)
  migrateLegacySubmissions();
}

// ── Subject Filter ───────────────────────────────────────────────────────────
function populateSubjectFilter() {
  const sel = document.getElementById('filterSubject');
  if (!sel) return;
  sel.innerHTML = '<option value="all">All Subjects</option>';
  const subjects = new Set();
  allSubmissions.forEach(s => {
    if (s.subject) subjects.add(s.subject);
  });
  subjects.forEach(subj => {
    const o = document.createElement('option');
    o.value = subj;
    o.textContent = subj;
    sel.appendChild(o);
  });
}

window.applyFilters = () => {
  const subject = document.getElementById('filterSubject')?.value || 'all';
  const set = document.getElementById('filterSet')?.value || 'all';
  const status = document.getElementById('filterStatus')?.value || 'all';

  filteredSubs = allSubmissions.filter(s => {
    if (subject !== 'all' && s.subject !== subject) return false;
    if (set !== 'all' && s.set_label !== set) return false;
    if (status === 'pass' && !s.pass_flag) return false;
    if (status === 'fail' && s.pass_flag) return false;
    return true;
  });

  updateKPIs();
  renderCharts();
  renderAIAnalysis();
  renderRankings();
  renderTable();
};

window.refreshDashboard = () => { destroyCharts(); initDashboard(); };

// ── KPIs ─────────────────────────────────────────────────────────────────────
function updateKPIs() {
  const subs = filteredSubs;
  if (!subs.length) return;

  const examsTaken = subs.length;
  const avgScore = Math.round(subs.reduce((a, s) => a + s.score_pct, 0) / subs.length);
  const passRate = Math.round(subs.filter(s => s.pass_flag).length / subs.length * 100);
  const avgTime = Math.round(subs.reduce((a, s) => a + s.time_taken_sec, 0) / subs.length / 60);

  document.getElementById('kpiStudents').textContent = examsTaken;
  document.getElementById('kpiSubmissions').textContent = subs.length;
  document.getElementById('kpiAvgScore').textContent = avgScore + '%';
  document.getElementById('kpiPassRate').textContent = passRate + '%';
  document.getElementById('kpiAvgTime').textContent = avgTime + 'm';

  // Update "Your Rank" KPI
  const rankVal = document.getElementById('kpiRankValue');
  const rankHint = document.getElementById('kpiRankHint');
  if (rankVal) {
    if (leaderboardData && leaderboardData.my_rank !== '\u2014' && typeof leaderboardData.my_rank === 'number') {
      rankVal.textContent = `#${leaderboardData.my_rank}`;
      if (rankHint) rankHint.textContent = `of ${leaderboardData.total_ranked} ranked`;
    } else {
      rankVal.textContent = '\u2014';
      if (rankHint) rankHint.textContent = 'score at least 30% on average to enter the leaderboard';
    }
  }
}

// ── Charts ────────────────────────────────────────────────────────────────────
function destroyCharts() { Object.values(charts).forEach(c => { try { c.destroy(); } catch {} }); charts = {}; }

function renderCharts() {
  destroyCharts();
  const subs = filteredSubs;
  if (!subs.length) return;

  // Topic Radar — built from topic_breakdown if available, else from subject scores
  const topicMap = {};
  subs.forEach(s => {
    // Use subject as a topic grouping for the radar chart
    const subj = s.subject || 'General';
    if (!topicMap[subj]) topicMap[subj] = { e: 0, tot: 0, count: 0 };
    topicMap[subj].e += s.score_pct;
    topicMap[subj].tot += 100;
    topicMap[subj].count += 1;
  });
  const tLabels = Object.keys(topicMap);
  const tData = tLabels.map(t => topicMap[t].count > 0 ? Math.round(topicMap[t].e / topicMap[t].count) : 0);
  charts.topic = new Chart(document.getElementById('topicChart'), {
    type: 'radar',
    data: {
      labels: tLabels,
      datasets: [{ label: 'Avg %', data: tData, backgroundColor: 'rgba(124,58,237,0.15)', borderColor: '#a855f7', pointBackgroundColor: '#a855f7', borderWidth: 2, pointRadius: 4 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: CHART_DEFAULTS.color } } }, scales: { r: { grid: { color: CHART_DEFAULTS.grid }, ticks: { color: CHART_DEFAULTS.muted, backdropColor: 'transparent', font: { size: 9 } }, pointLabels: { color: CHART_DEFAULTS.color, font: { size: 10 } }, min: 0, max: 100 } } }
  });

  // Set-wise bar chart
  const setLabels = ['Set A', 'Set B', 'Set C', 'Set D'];
  const setValues = ['Set A', 'Set B', 'Set C', 'Set D'].map(label => {
    const f = subs.filter(s => s.set_label === label);
    return f.length ? Math.round(f.reduce((a, s) => a + s.score_pct, 0) / f.length) : 0;
  });
  charts.set = new Chart(document.getElementById('setChart'), {
    type: 'bar',
    data: { labels: setLabels, datasets: [{ label: 'Avg Score %', data: setValues, backgroundColor: ['rgba(124,58,237,0.7)', 'rgba(37,99,235,0.7)', 'rgba(8,145,178,0.7)', 'rgba(5,150,105,0.7)'], borderRadius: 6, borderSkipped: false }] },
    options: { ...baseChartOpts(), plugins: { legend: { display: false } } }
  });

  // Pass vs Fail doughnut
  const pass = subs.filter(s => s.pass_flag).length;
  charts.pass = new Chart(document.getElementById('passChart'), {
    type: 'doughnut',
    data: { labels: ['Pass', 'Fail'], datasets: [{ data: [pass, subs.length - pass], backgroundColor: ['rgba(5,150,105,0.8)', 'rgba(220,38,38,0.8)'], borderWidth: 0, hoverOffset: 6 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: CHART_DEFAULTS.color, padding: 12 } } } }
  });
}

function baseChartOpts() {
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { labels: { color: CHART_DEFAULTS.color } } },
    scales: {
      x: { grid: { color: CHART_DEFAULTS.grid }, ticks: { color: CHART_DEFAULTS.muted } },
      y: { grid: { color: CHART_DEFAULTS.grid }, ticks: { color: CHART_DEFAULTS.muted }, beginAtZero: true }
    }
  };
}

// ── AI Analysis ───────────────────────────────────────────────────────────────
function renderAIAnalysis() {
  const subs = filteredSubs;
  if (!subs.length) return;

  document.getElementById('aiAnalysisFor').textContent = `Analyzing ${subs.length} submission(s)`;

  // Build topic map from subjects for AI analysis
  const topicMap = {};
  subs.forEach(s => {
    const subj = s.subject || 'General';
    if (!topicMap[subj]) topicMap[subj] = { e: 0, tot: 0, count: 0 };
    topicMap[subj].e += s.score_pct;
    topicMap[subj].tot += 100;
    topicMap[subj].count += 1;
  });

  const strong = [], canImprove = [], weak = [];
  Object.entries(topicMap).forEach(([t, sc]) => {
    const p = sc.count > 0 ? Math.round(sc.e / sc.count) : 0;
    if (p >= 70) strong.push({ topic: t, pct: p });
    else if (p >= 40) canImprove.push({ topic: t, pct: p });
    else weak.push({ topic: t, pct: p });
  });

  const renderZone = (id, items) => {
    document.getElementById(id).innerHTML = items.length
      ? items.map(i => `<li class="zone-item"><span class="zone-item-name">${i.topic}</span><span class="zone-item-pct">${i.pct}%</span></li>`).join('')
      : '<li class="zone-item"><span class="zone-item-name" style="color:var(--muted)">No data</span></li>';
  };

  renderZone('strongItems', strong);
  renderZone('improveItems', canImprove);
  renderZone('weakItems', weak);
  document.getElementById('strongCount').textContent = strong.length;
  document.getElementById('improveCount').textContent = canImprove.length;
  document.getElementById('weakCount').textContent = weak.length;

  const avgScore = Math.round(subs.reduce((a, s) => a + s.score_pct, 0) / subs.length);
  const passRate = Math.round(subs.filter(s => s.pass_flag).length / subs.length * 100);
  let rec = '';
  if (avgScore >= 75) rec = `🎉 Outstanding performance! Average score is ${avgScore}% with a ${passRate}% pass rate. `;
  else if (avgScore >= 60) rec = `👍 Good performance overall. Average score is ${avgScore}%. `;
  else if (avgScore >= 40) rec = `📚 Moderate performance. Average score is ${avgScore}%. More practice needed. `;
  else rec = `⚠️ Performance needs significant improvement. Average score is ${avgScore}%. `;
  if (weak.length) rec += `Priority focus areas: ${weak.map(w => w.topic).join(', ')}. `;
  if (canImprove.length) rec += `Topics with growth potential: ${canImprove.map(c => c.topic).join(', ')}. `;
  if (strong.length) rec += `Strong topics to maintain: ${strong.map(s => s.topic).join(', ')}.`;

  document.getElementById('aiRecommendationText').textContent = rec;
}

// ── Results Table ─────────────────────────────────────────────────────────────
function renderTable() {
  const search = document.getElementById('searchInput')?.value.toLowerCase() || '';
  let subs = filteredSubs.filter(s =>
    (s.subject || '').toLowerCase().includes(search) ||
    (s.set_label || '').toLowerCase().includes(search)
  );

  subs.sort((a, b) => {
    let va, vb;
    if (sortKey === 'score') { va = a.score_pct; vb = b.score_pct; }
    else if (sortKey === 'time') { va = a.time_taken_sec; vb = b.time_taken_sec; }
    else if (sortKey === 'subject') { va = a.subject || ''; vb = b.subject || ''; }
    else if (sortKey === 'set') { va = a.set_label || ''; vb = b.set_label || ''; }
    else if (sortKey === 'status') { va = a.pass_flag ? 1 : 0; vb = b.pass_flag ? 1 : 0; }
    else if (sortKey === 'submitted_at') { va = a.submitted_at || ''; vb = b.submitted_at || ''; }
    else { va = a.score_pct; vb = b.score_pct; }
    if (va < vb) return sortDir; if (va > vb) return -sortDir; return 0;
  });

  const tbody = document.getElementById('resultsBody');
  tbody.innerHTML = subs.map(s => {
    const p = Math.round(s.score_pct);
    const cls = p >= 70 ? 'score-high' : p >= 40 ? 'score-mid' : 'score-low';
    const m = Math.floor(s.time_taken_sec / 60), sec = s.time_taken_sec % 60;
    const date = s.submitted_at ? new Date(s.submitted_at).toLocaleDateString() : '—';
    return `<tr>
      <td><span style="font-weight:700;color:var(--purple-l)">${s.subject || '—'}</span></td>
      <td><span style="font-weight:600">${s.set_label || '—'}</span></td>
      <td><span class="score-badge ${cls}">${p}%</span></td>
      <td style="color:var(--muted)">${m}m ${sec}s</td>
      <td class="${s.pass_flag ? 'status-pass' : 'status-fail'}">${s.pass_flag ? '✅ Pass' : '❌ Fail'}</td>
      <td style="color:var(--muted2)">${date}</td>
      <td><button class="btn-view" onclick="openDrawer('${s.id}')">View →</button></td>
    </tr>`;
  }).join('');

  document.getElementById('tableFooter').textContent = `Showing ${subs.length} of ${allSubmissions.length} submissions`;
}

window.filterTable = () => renderTable();
window.sortTable = key => { if (sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = -1; } renderTable(); };

// ── Rankings (Top 3 only for student dashboard) ──────────────────────────────
function renderRankings() {
  const medals = ['🥇', '🥈', '🥉'];

  // Use leaderboard API data for top 3
  if (!leaderboardData || !leaderboardData.top_3 || leaderboardData.top_3.length === 0) {
    document.getElementById('rankingBody').innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:24px">No ranking data available yet</td></tr>';
    // Hide ranking chart when no data
    if (charts.ranking) { try { charts.ranking.destroy(); } catch {} }
    return;
  }

  const top3 = leaderboardData.top_3;

  // Bar chart for top 3
  if (charts.ranking) { try { charts.ranking.destroy(); } catch {} }
  charts.ranking = new Chart(document.getElementById('rankingChart'), {
    type: 'bar',
    data: {
      labels: top3.map(s => s.display_name),
      datasets: [{
        label: 'Composite Score',
        data: top3.map(s => Math.round(s.composite_score)),
        backgroundColor: top3.map((s, i) => {
          if (i === 0) return 'rgba(255,215,0,0.8)';
          if (i === 1) return 'rgba(192,192,192,0.8)';
          return 'rgba(205,127,50,0.8)';
        }),
        borderRadius: 6,
        borderSkipped: false
      }]
    },
    options: {
      ...baseChartOpts(),
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: CHART_DEFAULTS.grid }, ticks: { color: CHART_DEFAULTS.color } },
        y: { grid: { color: CHART_DEFAULTS.grid }, ticks: { color: CHART_DEFAULTS.muted }, min: 0, max: 100, beginAtZero: true }
      }
    }
  });

  // Render top 3 table rows with medal indicators
  document.getElementById('rankingBody').innerHTML = top3.map((s, i) => {
    const score = Math.round(s.composite_score);
    const cls = score >= 70 ? 'score-high' : score >= 40 ? 'score-mid' : 'score-low';
    const medal = medals[i] || `#${s.rank}`;
    return `<tr>
      <td style="font-size:1.1rem;text-align:center">${medal}</td>
      <td><div style="font-weight:700">${s.display_name}</div></td>
      <td style="color:var(--muted)">${s.kcet_student_id}</td>
      <td><span class="score-badge ${cls}">${score}</span></td>
      <td style="min-width:140px">
        <div style="background:var(--s3);border-radius:4px;height:8px;overflow:hidden">
          <div style="width:${score}%;height:100%;border-radius:4px;background:${score >= 70 ? 'var(--green-l)' : score >= 40 ? 'var(--yellow-l)' : 'var(--red-l)'};transition:width 0.6s ease"></div>
        </div>
      </td>
    </tr>`;
  }).join('');
}

// ── Detail Drawer ─────────────────────────────────────────────────────────────
window.openDrawer = async (submissionId) => {
  try {
    const res = await fetch(`/api/student/submissions/${submissionId}`, { credentials: 'include' });
    if (!res.ok) {
      showToast('Failed to load submission details');
      return;
    }
    const s = await res.json();

    document.getElementById('drawerName').textContent = s.subject || 'Exam';
    document.getElementById('drawerMeta').textContent = `${s.set_label || ''} · ${new Date(s.submitted_at).toLocaleString()}`;

    const m = Math.floor(s.time_taken_sec / 60), sec = s.time_taken_sec % 60;
    const icons = { correct: '✅', wrong: '❌', partial: '🟡', unanswered: '⬜' };

    document.getElementById('drawerBody').innerHTML = `
      <div class="drawer-kpi-row">
        <div class="drawer-kpi"><div class="drawer-kpi-val">${Math.round(s.score_pct)}%</div><div class="drawer-kpi-label">Score</div></div>
        <div class="drawer-kpi"><div class="drawer-kpi-val">${m}m ${sec}s</div><div class="drawer-kpi-label">Time</div></div>
        <div class="drawer-kpi"><div class="drawer-kpi-val">${s.pass_flag ? '✅ Pass' : '❌ Fail'}</div><div class="drawer-kpi-label">Status</div></div>
      </div>
      <div class="drawer-section-title">Answer Review (${s.questions?.length || 0} questions)</div>
      <div class="answer-review-list">
        ${(s.questions || []).map((r, i) => `
          <div class="answer-row ${r.status}">
            <span class="ans-status-icon">${icons[r.status] || '⬜'}</span>
            <div class="ans-content">
              <div class="ans-q-text">Q${r.order_index != null ? r.order_index + 1 : i + 1}. ${r.q}</div>
              <div class="ans-given">Your answer: <strong>${r.given !== undefined && r.given !== null && r.given !== '' ? r.given : 'Not answered'}</strong></div>
              ${r.status !== 'correct' ? `<div class="ans-correct-text">✓ Correct: ${r.correctAns}</div>` : ''}
              <div class="ans-meta">${r.topic}</div>
            </div>
          </div>`).join('')}
      </div>`;

    document.getElementById('drawerOverlay').style.display = 'block';
    document.getElementById('detailDrawer').classList.add('open');
  } catch (e) {
    console.error('Error opening drawer:', e);
    showToast('Error loading submission details');
  }
};

window.closeDrawer = () => {
  document.getElementById('drawerOverlay').style.display = 'none';
  document.getElementById('detailDrawer').classList.remove('open');
};

// ── Export ────────────────────────────────────────────────────────────────────
window.exportReport = () => {
  const subs = filteredSubs;
  if (!subs.length) { showToast('No data to export'); return; }
  let csv = 'Subject,Set,Score%,Time(s),Status,Date\n';
  subs.forEach(s => {
    const date = s.submitted_at ? new Date(s.submitted_at).toLocaleDateString() : '';
    csv += `"${s.subject || ''}","${s.set_label || ''}",${Math.round(s.score_pct)},${s.time_taken_sec},${s.pass_flag ? 'Pass' : 'Fail'},"${date}"\n`;
  });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `SmartKCET_Report_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  showToast('📊 Report exported as CSV', 'success');
};

// Remove clearAllData — no longer relevant for server-backed dashboard

// ── Boot ──────────────────────────────────────────────────────────────────────
// Utility: showToast (self-contained, no dependency on app.js)
function showToast(msg, type = '') {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t?.remove(), 3500);
}

// ── Legacy localStorage Migration (REQ-14.1, REQ-14.4) ──────────────────────
/**
 * Detect legacy `ef_submissions` entries in localStorage and attempt to
 * upload them to /api/student/submit. On success, clear the legacy key.
 * On failure (not authenticated, server error), leave data for next attempt.
 */
async function migrateLegacySubmissions() {
  var raw = localStorage.getItem('ef_submissions');
  if (!raw) return;

  var submissions;
  try {
    submissions = JSON.parse(raw);
  } catch (e) {
    // Corrupted data — remove it
    localStorage.removeItem('ef_submissions');
    return;
  }

  if (!Array.isArray(submissions) || submissions.length === 0) {
    localStorage.removeItem('ef_submissions');
    return;
  }

  var allSucceeded = true;

  for (var i = 0; i < submissions.length; i++) {
    var sub = submissions[i];
    // Generate a deterministic idempotency key from the legacy data to prevent duplicates
    var idempotencyKey = 'legacy-' + (sub.id || sub.timestamp || Date.now() + '-' + i);

    var body = {
      exam_set_id: sub.exam_set_id || null,
      answers: sub.answers || {},
      time_taken_sec: typeof sub.time_taken_sec === 'number' ? sub.time_taken_sec : 0,
      idempotency_key: idempotencyKey,
    };

    // Skip entries without a valid exam_set_id (can't submit without one)
    if (!body.exam_set_id) {
      continue;
    }

    try {
      var res = await fetch('/api/student/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        // Not authenticated or server error — leave data for next attempt
        allSucceeded = false;
        break;
      }
    } catch (e) {
      // Network error — leave data for next attempt
      allSucceeded = false;
      break;
    }
  }

  if (allSucceeded) {
    localStorage.removeItem('ef_submissions');
  }
}

initDashboard();
