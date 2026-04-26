// ═══════════════════════════════════════════════════════════════════════════
// DASHBOARD PAGE LOGIC — Standalone Analytics
// ═══════════════════════════════════════════════════════════════════════════
let charts = {};
let allSubmissions = [];
let filteredSubs = [];
let sortKey = 'score';
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
function initDashboard() {
  allSubmissions = Store.get('submissions') || [];
  document.getElementById('lastUpdated').textContent = `Last updated: ${new Date().toLocaleTimeString()}`;

  if (allSubmissions.length === 0) {
    document.getElementById('emptyState').style.display = 'block';
    document.getElementById('dashContent').style.display = 'none';
    return;
  }

  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('dashContent').style.display = 'block';

  populateStudentFilter();
  applyFilters();
}

function populateStudentFilter() {
  const sel = document.getElementById('filterStudent');
  sel.innerHTML = '<option value="all">All Students</option>';
  const seen = new Set();
  allSubmissions.forEach(s => {
    if (!seen.has(s.student.roll)) {
      seen.add(s.student.roll);
      const o = document.createElement('option');
      o.value = s.student.roll;
      o.textContent = `${s.student.name} (${s.student.roll})`;
      sel.appendChild(o);
    }
  });
}

window.applyFilters = () => {
  const roll = document.getElementById('filterStudent').value;
  const set = document.getElementById('filterSet').value;
  const status = document.getElementById('filterStatus').value;

  filteredSubs = allSubmissions.filter(s => {
    if (roll !== 'all' && s.student.roll !== roll) return false;
    if (set !== 'all' && s.setIndex !== parseInt(set)) return false;
    if (status === 'pass' && !s.result.pass) return false;
    if (status === 'fail' && s.result.pass) return false;
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
  const students = new Set(subs.map(s => s.student.roll)).size;
  const avgScore = Math.round(subs.reduce((a,s) => a + s.result.percentage, 0) / subs.length);
  const passRate = Math.round(subs.filter(s => s.result.pass).length / subs.length * 100);
  const avgTime = Math.round(subs.reduce((a,s) => a + s.timeTaken, 0) / subs.length / 60);

  document.getElementById('kpiStudents').textContent = students;
  document.getElementById('kpiSubmissions').textContent = subs.length;
  document.getElementById('kpiAvgScore').textContent = avgScore + '%';
  document.getElementById('kpiPassRate').textContent = passRate + '%';
  document.getElementById('kpiAvgTime').textContent = avgTime + 'm';
}

// ── Charts ────────────────────────────────────────────────────────────────────
function destroyCharts() { Object.values(charts).forEach(c => { try { c.destroy(); } catch {} }); charts = {}; }

function renderCharts() {
  destroyCharts();
  const subs = filteredSubs;
  if (!subs.length) return;

  // Topic Radar
  const topicMap = {};
  subs.forEach(s => Object.entries(s.result.topicScores || {}).forEach(([t,sc]) => {
    if (!topicMap[t]) topicMap[t] = { e:0, tot:0 };
    topicMap[t].e += sc.earned; topicMap[t].tot += sc.total;
  }));
  const tLabels = Object.keys(topicMap);
  const tData = tLabels.map(t => topicMap[t].tot > 0 ? Math.round(topicMap[t].e/topicMap[t].tot*100) : 0);
  charts.topic = new Chart(document.getElementById('topicChart'), {
    type: 'radar',
    data: {
      labels: tLabels,
      datasets: [{ label: 'Avg %', data: tData, backgroundColor: 'rgba(124,58,237,0.15)', borderColor: '#a855f7', pointBackgroundColor: '#a855f7', borderWidth: 2, pointRadius: 4 }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: CHART_DEFAULTS.color } } }, scales: { r: { grid: { color: CHART_DEFAULTS.grid }, ticks: { color: CHART_DEFAULTS.muted, backdropColor: 'transparent', font: { size: 9 } }, pointLabels: { color: CHART_DEFAULTS.color, font: { size: 10 } }, min: 0, max: 100 } } }
  });

  // Set-wise
  const setData = [0,1,2,3].map(i => {
    const f = subs.filter(s => s.setIndex === i);
    return f.length ? Math.round(f.reduce((a,s)=>a+s.result.percentage,0)/f.length) : 0;
  });
  charts.set = new Chart(document.getElementById('setChart'), {
    type: 'bar',
    data: { labels: ['Set A','Set B','Set C','Set D'], datasets: [{ label: 'Avg Score %', data: setData, backgroundColor: ['rgba(124,58,237,0.7)','rgba(37,99,235,0.7)','rgba(8,145,178,0.7)','rgba(5,150,105,0.7)'], borderRadius: 6, borderSkipped: false }] },
    options: { ...baseChartOpts(), plugins: { legend: { display: false } } }
  });

  // Pass vs Fail
  const pass = subs.filter(s => s.result.pass).length;
  charts.pass = new Chart(document.getElementById('passChart'), {
    type: 'doughnut',
    data: { labels: ['Pass','Fail'], datasets: [{ data: [pass, subs.length-pass], backgroundColor: ['rgba(5,150,105,0.8)','rgba(220,38,38,0.8)'], borderWidth: 0, hoverOffset: 6 }] },
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

  const roll = document.getElementById('filterStudent').value;
  document.getElementById('aiAnalysisFor').textContent = roll === 'all' ? `Analyzing ${subs.length} submission(s)` : `Analyzing ${subs[0]?.student.name}`;

  const topicMap = {};
  subs.forEach(s => Object.entries(s.result.topicScores || {}).forEach(([t,sc]) => {
    if (!topicMap[t]) topicMap[t] = { e:0, tot:0 };
    topicMap[t].e += sc.earned; topicMap[t].tot += sc.total;
  }));

  const strong = [], canImprove = [], weak = [];
  Object.entries(topicMap).forEach(([t,sc]) => {
    const p = sc.tot > 0 ? Math.round(sc.e/sc.tot*100) : 0;
    if (p >= 70) strong.push({ topic:t, pct:p });
    else if (p >= 40) canImprove.push({ topic:t, pct:p });
    else weak.push({ topic:t, pct:p });
  });

  const renderZone = (id, items) => {
    document.getElementById(id).innerHTML = items.length
      ? items.map(i=>`<li class="zone-item"><span class="zone-item-name">${i.topic}</span><span class="zone-item-pct">${i.pct}%</span></li>`).join('')
      : '<li class="zone-item"><span class="zone-item-name" style="color:var(--muted)">No data</span></li>';
  };

  renderZone('strongItems', strong);
  renderZone('improveItems', canImprove);
  renderZone('weakItems', weak);
  document.getElementById('strongCount').textContent = strong.length;
  document.getElementById('improveCount').textContent = canImprove.length;
  document.getElementById('weakCount').textContent = weak.length;

  const avgScore = Math.round(subs.reduce((a,s)=>a+s.result.percentage,0)/subs.length);
  const passRate = Math.round(subs.filter(s=>s.result.pass).length/subs.length*100);
  let rec = '';
  if (avgScore >= 75) rec = `🎉 Outstanding performance! Average score is ${avgScore}% with a ${passRate}% pass rate. `;
  else if (avgScore >= 60) rec = `👍 Good performance overall. Average score is ${avgScore}%. `;
  else if (avgScore >= 40) rec = `📚 Moderate performance. Average score is ${avgScore}%. More practice needed. `;
  else rec = `⚠️ Performance needs significant improvement. Average score is ${avgScore}%. `;
  if (weak.length) rec += `Priority focus areas: ${weak.map(w=>w.topic).join(', ')}. `;
  if (canImprove.length) rec += `Topics with growth potential: ${canImprove.map(c=>c.topic).join(', ')}. `;
  if (strong.length) rec += `Strong topics to maintain: ${strong.map(s=>s.topic).join(', ')}.`;

  document.getElementById('aiRecommendationText').textContent = rec;
}

// ── Results Table ─────────────────────────────────────────────────────────────
function renderTable() {
  const L = ['A','B','C','D'];
  const search = document.getElementById('searchInput')?.value.toLowerCase() || '';
  let subs = filteredSubs.filter(s =>
    s.student.name.toLowerCase().includes(search) ||
    s.student.roll.toLowerCase().includes(search)
  );

  subs.sort((a,b) => {
    let va, vb;
    if (sortKey==='score') { va=a.result.percentage; vb=b.result.percentage; }
    else if (sortKey==='time') { va=a.timeTaken; vb=b.timeTaken; }
    else if (sortKey==='name') { va=a.student.name; vb=b.student.name; }
    else if (sortKey==='set') { va=a.setIndex; vb=b.setIndex; }
    else if (sortKey==='status') { va=a.result.pass?1:0; vb=b.result.pass?1:0; }
    else { va=a.result.percentage; vb=b.result.percentage; }
    if (va < vb) return sortDir; if (va > vb) return -sortDir; return 0;
  });

  const tbody = document.getElementById('resultsBody');
  tbody.innerHTML = subs.map(s => {
    const p = s.result.percentage;
    const cls = p>=70?'score-high':p>=40?'score-mid':'score-low';
    const m = Math.floor(s.timeTaken/60), sec = s.timeTaken%60;
    return `<tr>
      <td><div style="font-weight:600">${s.student.name}</div></td>
      <td style="color:var(--muted)">${s.student.roll}</td>
      <td><span style="font-weight:700;color:var(--purple-l)">Set ${L[s.setIndex]}</span></td>
      <td><span class="score-badge ${cls}">${p}%</span></td>
      <td style="color:var(--muted2)">${s.result.earnedMarks ?? s.result.earned}/${s.result.totalMarks ?? s.result.total}</td>
      <td style="color:var(--muted)">${m}m ${sec}s</td>
      <td class="${s.result.pass?'status-pass':'status-fail'}">${s.result.pass?'✅ Pass':'❌ Fail'}</td>
      <td><button class="btn-view" onclick="openDrawer(${s.id})">View →</button></td>
    </tr>`;
  }).join('');

  document.getElementById('tableFooter').textContent = `Showing ${subs.length} of ${allSubmissions.length} submissions`;
}

window.filterTable = () => renderTable();
window.sortTable = key => { if (sortKey===key) sortDir*=-1; else { sortKey=key; sortDir=-1; } renderTable(); };

// ── Rankings ──────────────────────────────────────────────────────────────────
function renderRankings() {
  const L = ['A','B','C','D'];
  const medals = ['🥇','🥈','🥉'];

  const studentBest = {};
  filteredSubs.forEach(s => {
    const roll = s.student.roll;
    if (!studentBest[roll] || s.result.percentage > studentBest[roll].result.percentage) {
      studentBest[roll] = s;
    }
  });

  const ranked = Object.values(studentBest).sort((a,b) => b.result.percentage - a.result.percentage);

  // Bar chart
  if (charts.ranking) { try { charts.ranking.destroy(); } catch {} }
  charts.ranking = new Chart(document.getElementById('rankingChart'), {
    type: 'bar',
    data: {
      labels: ranked.map(s => s.student.name),
      datasets: [{
        label: 'Score %',
        data: ranked.map(s => s.result.percentage),
        backgroundColor: ranked.map(s => {
          const p = s.result.percentage;
          return p >= 70 ? 'rgba(52,211,153,0.8)' : p >= 40 ? 'rgba(251,191,36,0.8)' : 'rgba(248,113,113,0.8)';
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

  document.getElementById('rankingBody').innerHTML = ranked.map((s, i) => {
    const p = s.result.percentage;
    const cls = p>=70?'score-high':p>=40?'score-mid':'score-low';
    const medal = medals[i] || `#${i+1}`;
    return `<tr>
      <td style="font-size:1.1rem;text-align:center">${medal}</td>
      <td><div style="font-weight:700">${s.student.name}</div></td>
      <td style="color:var(--muted)">${s.student.roll}</td>
      <td><span class="score-badge ${cls}">${p}%</span></td>
      <td style="min-width:140px">
        <div style="background:var(--s3);border-radius:4px;height:8px;overflow:hidden">
          <div style="width:${p}%;height:100%;border-radius:4px;background:${p>=70?'var(--green-l)':p>=40?'var(--yellow-l)':'var(--red-l)'};transition:width 0.6s ease"></div>
        </div>
      </td>
      <td style="color:var(--muted2)">${s.result.earnedMarks ?? s.result.earned}/${s.result.totalMarks ?? s.result.total}</td>
      <td><span style="font-weight:700;color:var(--purple-l)">Set ${L[s.setIndex]}</span></td>
      <td class="${s.result.pass?'status-pass':'status-fail'}">${s.result.pass?'✅ Pass':'❌ Fail'}</td>
    </tr>`;
  }).join('');
}

// ── Detail Drawer ─────────────────────────────────────────────────────────────
window.openDrawer = id => {
  const s = allSubmissions.find(x => x.id === id);
  if (!s) return;
  const L = ['A','B','C','D'];
  document.getElementById('drawerName').textContent = s.student.name;
  document.getElementById('drawerMeta').textContent = `${s.student.roll} · Set ${L[s.setIndex]} · ${s.difficulty} · ${new Date(s.submittedAt).toLocaleString()}`;

  const m = Math.floor(s.timeTaken/60), sec = s.timeTaken%60;
  const icons = { correct:'✅', wrong:'❌', partial:'🟡', unanswered:'⬜' };

  document.getElementById('drawerBody').innerHTML = `
    <div class="drawer-kpi-row">
      <div class="drawer-kpi"><div class="drawer-kpi-val">${s.result.percentage}%</div><div class="drawer-kpi-label">Score</div></div>
      <div class="drawer-kpi"><div class="drawer-kpi-val">${s.result.earnedMarks ?? s.result.earned}/${s.result.totalMarks ?? s.result.total}</div><div class="drawer-kpi-label">Marks</div></div>
      <div class="drawer-kpi"><div class="drawer-kpi-val">${m}m ${sec}s</div><div class="drawer-kpi-label">Time</div></div>
    </div>
    <div class="drawer-section-title">AI Analysis</div>
    <div style="background:var(--s2);border-radius:var(--rs);padding:14px;font-size:0.82rem;color:var(--muted2);line-height:1.7;margin-bottom:16px">
      ${s.result.recommendation || 'No AI recommendation available.'}
    </div>
    <div class="drawer-section-title">Answer Review (${s.result.questionResults?.length || 0} questions)</div>
    <div class="answer-review-list">
      ${(s.result.questionResults || []).map((r,i) => `
        <div class="answer-row ${r.status}">
          <span class="ans-status-icon">${icons[r.status]||'⬜'}</span>
          <div class="ans-content">
            <div class="ans-q-text">Q${i+1}. ${r.q}</div>
            <div class="ans-given">Your answer: <strong>${r.given !== undefined && r.given !== '' ? r.given : 'Not answered'}</strong></div>
            ${r.status !== 'correct' ? `<div class="ans-correct-text">✓ Correct: ${r.correctAns}</div>` : ''}
            <div class="ans-meta">${r.topic} · ${r.type} · ${r.earned}/${r.marks} marks</div>
          </div>
        </div>`).join('')}
    </div>`;

  document.getElementById('drawerOverlay').style.display = 'block';
  document.getElementById('detailDrawer').classList.add('open');
};

window.closeDrawer = () => {
  document.getElementById('drawerOverlay').style.display = 'none';
  document.getElementById('detailDrawer').classList.remove('open');
};

// ── Export ────────────────────────────────────────────────────────────────────
window.exportReport = () => {
  const subs = filteredSubs;
  if (!subs.length) { showToast('No data to export'); return; }
  const L = ['A','B','C','D'];
  let csv = 'Name,Roll,Set,Score%,Marks,Time(s),Difficulty,Status\n';
  subs.forEach(s => {
    csv += `"${s.student.name}","${s.student.roll}","Set ${L[s.setIndex]}",${s.result.percentage},${s.result.earnedMarks ?? s.result.earned}/${s.result.totalMarks ?? s.result.total},${s.timeTaken},${s.difficulty},${s.result.pass?'Pass':'Fail'}\n`;
  });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a.download = `ExamForge_Report_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  showToast('📊 Report exported as CSV', 'success');
};

window.clearAllData = () => {
  if (!confirm('Clear all submission data? This cannot be undone.')) return;
  Store.del('submissions');
  destroyCharts();
  initDashboard();
  showToast('🗑️ All data cleared');
};

// ── Boot ──────────────────────────────────────────────────────────────────────
initDashboard();
