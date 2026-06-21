// ═══════════════════════════════════════════════════════════════════════════
// DIRECT SUBSCRIBER PERFORMANCE PAGE LOGIC
// Fetches data from /api/student/submissions and /api/student/leaderboard/me
// Specialized view for direct_subscriber users with performance analytics
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
async function initPerformancePage() {
  console.log('='.repeat(80));
  console.log('[performance] ========== PERFORMANCE PAGE INIT START ==========');
  console.log('[performance] Timestamp:', new Date().toISOString());
  console.log('='.repeat(80));
  
  // Initialize the persistent subscription banner
  if (typeof SubscriptionBanner !== 'undefined' && SubscriptionBanner.init) {
    try { SubscriptionBanner.init(); } catch (e) { console.error('Banner init failed:', e); }
  }

  // STEP 1: Detect role and subtype
  console.log('[performance] STEP 1: Verifying user is direct_subscriber...');
  let currentUserRole = null;
  let currentUserSubtype = null;
  let userInfo = null;
  
  try {
    if (typeof Auth !== 'undefined' && Auth.currentRole) {
      userInfo = await Auth.currentRole();
      currentUserRole = userInfo && userInfo.role;
      currentUserSubtype = userInfo && userInfo.student_subtype;
      
      console.log('[performance] User info received:');
      console.log('[performance]   → role:', currentUserRole);
      console.log('[performance]   → student_subtype:', currentUserSubtype);
    } else {
      console.error('[performance] Auth module NOT available!');
    }
  } catch (e) { 
    console.error('[performance] Error fetching user info:', e);
  }

  // ── Access Control: Only direct_subscriber can access this page ──────────
  console.log('[performance] STEP 2: Checking access control...');
  
  if (currentUserRole !== 'student') {
    console.error('[performance] ❌ Access denied: Not a student. Redirecting...');
    window.location.replace('/dashboard');
    return;
  }
  
  if (currentUserSubtype !== 'direct_subscriber') {
    console.error('[performance] ❌ Access denied: Not a direct_subscriber. Redirecting...');
    window.location.replace('/dashboard');
    return;
  }
  
  console.log('[performance] ✅ Access control passed - direct_subscriber verified');

  // ── Populate Student Profile Card ──────────────────────────────────────
  if (userInfo) {
    const displayName = userInfo.display_name || userInfo.sub || '—';
    const kcetId = userInfo.kcet_student_id || '—';
    
    const studentNameEl = document.getElementById('studentName');
    const studentIdEl = document.getElementById('studentKcetId');
    
    if (studentNameEl) studentNameEl.textContent = displayName;
    if (studentIdEl) studentIdEl.textContent = kcetId;
    
    console.log('[performance] Student profile populated:', { displayName, kcetId });
  }

  try {
    // Fetch submissions from API
    console.log('[performance] STEP 3: Fetching submissions...');
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
    console.log('[performance] Submissions fetched:', allSubmissions.length, 'records');

    // Fetch leaderboard data
    console.log('[performance] STEP 4: Fetching leaderboard data...');
    try {
      const lbRes = await fetch('/api/student/leaderboard/me', { credentials: 'include' });
      if (lbRes.ok) {
        leaderboardData = await lbRes.json();
        console.log('[performance] Leaderboard data fetched');
      }
    } catch (e) {
      console.warn('Leaderboard data unavailable:', e.message);
      leaderboardData = null;
    }
  } catch (e) {
    console.error('Performance page init error:', e);
    renderEmptyPerformance();
    return;
  }

  if (allSubmissions.length === 0) {
    console.log('[performance] No submissions found - rendering empty state');
    renderEmptyPerformance();
    return;
  }

  console.log('[performance] ✅ Data loaded successfully');
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('dashContent').style.display = 'block';

  populateSubjectFilter();
  applyFilters();
}

/**
 * Render the performance page skeleton with empty / zero values when the user has
 * no submission data yet.
 */
function renderEmptyPerformance() {
  const emptyEl = document.getElementById('emptyState');
  const dashEl = document.getElementById('dashContent');
  if (emptyEl) emptyEl.style.display = 'block';
  if (dashEl) dashEl.style.display = 'block';

  // Reset KPI tiles to a clear "no data" state.
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };
  setText('kpiStudents', '0');
  setText('kpiSubmissions', '0');
  setText('kpiAvgScore', '0%');
  setText('kpiPassRate', '0%');
  setText('kpiAvgTime', '0m');
  setText('kpiRankValue', '—');
  setText('kpiRankHint', 'Complete an exam to enter the leaderboard');

  // Render empty placeholders into the AI zones
  const emptyZone = '<li class="zone-item"><span class="zone-item-name" style="color:var(--muted)">No data yet</span></li>';
  ['strongItems', 'improveItems', 'weakItems'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = emptyZone;
  });
  setText('strongCount', 0);
  setText('improveCount', 0);
  setText('weakCount', 0);
  setText('aiAnalysisFor', 'No submissions to analyse yet');
  const recBox = document.getElementById('aiRecommendationText');
  if (recBox) {
    recBox.textContent = 'Take your first exam to receive personalised AI recommendations.';
  }

  const resultsBody = document.getElementById('resultsBody');
  if (resultsBody) {
    resultsBody.innerHTML =
      '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">No exam history yet — your submissions will appear here.</td></tr>';
  }
  setText('tableFooter', 'Showing 0 of 0 submissions');

  destroyCharts();
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
  renderTable();
};

window.refreshPerformancePage = () => { destroyCharts(); initPerformancePage(); };

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
  
  document.getElementById('lastUpdated').textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
}

// ── Charts ────────────────────────────────────────────────────────────────────
function destroyCharts() { 
  Object.values(charts).forEach(c => { 
    try { c.destroy(); } catch {} 
  }); 
  charts = {}; 
}

function renderCharts() {
  destroyCharts();
  const subs = filteredSubs;
  if (!subs.length) return;

  // Topic Radar — built from subject scores
  const topicMap = {};
  subs.forEach(s => {
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
      datasets: [{ label: 'Avg %', data: tData, backgroundColor: 'rgba(124,58,237,0.15)', borderColor: '#a855f7', pointBackgroundColor: '#a855f7', borderWidth: 2.5, pointRadius: 5, pointHoverRadius: 7 }]
    },
    options: { 
      responsive: true, 
      maintainAspectRatio: false, 
      plugins: { 
        legend: { 
          labels: { color: CHART_DEFAULTS.color, font: { size: 13, weight: 600 }, padding: 16 } 
        } 
      }, 
      scales: { 
        r: { 
          grid: { color: CHART_DEFAULTS.grid, lineWidth: 1.2 }, 
          ticks: { 
            color: CHART_DEFAULTS.muted, 
            backdropColor: 'transparent', 
            font: { size: 13, weight: 500 },
            padding: 8
          }, 
          pointLabels: { 
            color: CHART_DEFAULTS.color, 
            font: { size: 14, weight: 600 },
            padding: 12
          }, 
          min: 0, 
          max: 100 
        } 
      } 
    }
  });

  // Set-wise bar chart
  const setLabels = ['Set A', 'Set B', 'Set C', 'Set D'];
  const setValues = setLabels.map(label => {
    const f = subs.filter(s => s.set_label === label);
    return f.length ? Math.round(f.reduce((a, s) => a + s.score_pct, 0) / f.length) : 0;
  });
  
  charts.set = new Chart(document.getElementById('setChart'), {
    type: 'bar',
    data: { 
      labels: setLabels, 
      datasets: [{ label: 'Avg Score %', data: setValues, backgroundColor: ['rgba(124,58,237,0.7)', 'rgba(37,99,235,0.7)', 'rgba(8,145,178,0.7)', 'rgba(5,150,105,0.7)'], borderRadius: 6, borderSkipped: false }] 
    },
    options: { ...baseChartOpts(), plugins: { legend: { display: false } } }
  });

  // Pass vs Fail doughnut
  const pass = subs.filter(s => s.pass_flag).length;
  charts.pass = new Chart(document.getElementById('passChart'), {
    type: 'doughnut',
    data: { labels: ['Pass', 'Fail'], datasets: [{ data: [pass, subs.length - pass], backgroundColor: ['rgba(5,150,105,0.8)', 'rgba(220,38,38,0.8)'], borderWidth: 0, hoverOffset: 6 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: CHART_DEFAULTS.color, padding: 12 } } } }
  });

  // Score Trend Line Chart
  const sortedSubs = [...subs].sort((a, b) => new Date(a.submitted_at) - new Date(b.submitted_at));
  const last10 = sortedSubs.slice(-10);
  const trendLabels = last10.map((s, i) => `E${i + 1}`);
  const trendData = last10.map(s => s.score_pct);
  
  charts.trend = new Chart(document.getElementById('scoreChart'), {
    type: 'line',
    data: {
      labels: trendLabels,
      datasets: [{
        label: 'Score %',
        data: trendData,
        borderColor: '#a855f7',
        backgroundColor: 'rgba(124,58,237,0.05)',
        borderWidth: 3,
        pointBackgroundColor: '#a855f7',
        pointBorderColor: '#fff',
        pointBorderWidth: 2,
        pointRadius: 6,
        pointHoverRadius: 8,
        tension: 0.4,
        fill: true
      }]
    },
    options: {
      ...baseChartOpts(),
      plugins: { legend: { labels: { color: CHART_DEFAULTS.color, font: { size: 13, weight: 600 } } } },
      scales: {
        y: {
          ...baseChartOpts().scales.y,
          min: 0,
          max: 100
        }
      }
    }
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

  // AI Recommendation
  const recBox = document.getElementById('aiRecommendationText');
  if (recBox) {
    let recommendation = 'Keep working on weak areas and maintain your strong performance!';
    if (weak.length > 0) {
      recommendation = `Focus on improving ${weak[0].topic} (currently ${weak[0].pct}%). Your strong areas are ${strong.map(s => s.topic).join(', ')} — keep up the momentum!`;
    } else if (strong.length > 0) {
      recommendation = `Excellent work! You're excelling in ${strong.map(s => s.topic).join(', ')}. Keep practicing to maintain consistency.`;
    }
    recBox.textContent = recommendation;
  }
}

// ── Table Rendering ──────────────────────────────────────────────────────────
function renderTable() {
  const tbody = document.getElementById('resultsBody');
  if (!tbody) return;

  const displaySubs = filteredSubs.slice().sort((a, b) => {
    const aVal = a[sortKey];
    const bVal = b[sortKey];
    if (sortKey === 'submitted_at') {
      return sortDir * (new Date(bVal) - new Date(aVal));
    }
    if (aVal < bVal) return sortDir * -1;
    if (aVal > bVal) return sortDir * 1;
    return 0;
  });

  tbody.innerHTML = displaySubs.map(s => {
    const statusBadge = s.pass_flag 
      ? '<span style="color:#10b981;font-weight:600">✓ Pass</span>'
      : '<span style="color:#ef4444;font-weight:600">✗ Fail</span>';
    
    return `
      <tr>
        <td>${s.subject || '—'}</td>
        <td>${s.set_label || '—'}</td>
        <td><strong>${s.score_pct}%</strong></td>
        <td>${Math.round(s.time_taken_sec / 60)}m</td>
        <td>${statusBadge}</td>
        <td>${new Date(s.submitted_at).toLocaleDateString()}</td>
      </tr>
    `;
  }).join('');

  document.getElementById('tableFooter').textContent = `Showing ${displaySubs.length} of ${filteredSubs.length} submissions`;
}

window.sortTable = (key) => {
  if (sortKey === key) {
    sortDir = sortDir * -1;
  } else {
    sortKey = key;
    sortDir = -1;
  }
  renderTable();
};

window.filterTable = () => {
  const searchVal = (document.getElementById('searchInput')?.value || '').toLowerCase();
  if (!searchVal) {
    renderTable();
    return;
  }
  filteredSubs = allSubmissions.filter(s => {
    const subject = (s.subject || '').toLowerCase();
    const set = (s.set_label || '').toLowerCase();
    return subject.includes(searchVal) || set.includes(searchVal);
  });
  renderTable();
};

// ── Initialize on page load ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', initPerformancePage);
