// ExamForge AI — Core App Logic
// RAG API Integration Layer + Shared Utilities

// ── Local Storage Store ──────────────────────────────────────────────────────
const Store = {
  get: k => { try { return JSON.parse(localStorage.getItem('ef_' + k)); } catch { return null; } },
  set: (k, v) => localStorage.setItem('ef_' + k, JSON.stringify(v)),
  del: k => localStorage.removeItem('ef_' + k),
  clear: () => Object.keys(localStorage).filter(k => k.startsWith('ef_')).forEach(k => localStorage.removeItem(k))
};

// ── Configuration Check ──────────────────────────────────────────────────────
// Redirect to config page if backend not configured
(function checkConfig() {
  const cfg = Store.get('ragConfig');
  const currentPage = window.location.pathname;
  const isConfigPage = currentPage.includes('config.html');
  
  if (!cfg || !cfg.endpoint) {
    if (!isConfigPage && currentPage.includes('.html')) {
      window.location.href = './config.html';
    }
  }
})();

// ── RAG API Client ───────────────────────────────────────────────────────────
const RAG = {
  getConfig: () => Store.get('ragConfig') || { endpoint: '', apiKey: '' },

  headers() {
    const cfg = this.getConfig();
    const h = { 'Content-Type': 'application/json' };
    if (cfg.apiKey) h['Authorization'] = `Bearer ${cfg.apiKey}`;
    return h;
  },

  async health() {
    const cfg = this.getConfig();
    if (!cfg.endpoint) throw new Error('No endpoint configured');
    const res = await fetch(`${cfg.endpoint}/health`, { headers: this.headers() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  // POST /api/upload — send PYQ files to RAG backend
  async uploadDocs(files) {
    const cfg = this.getConfig();
    if (!cfg.endpoint) throw new Error('RAG endpoint not configured');
    const form = new FormData();
    files.forEach(f => form.append('files', f));
    const h = {};
    if (cfg.apiKey) h['Authorization'] = `Bearer ${cfg.apiKey}`;
    const res = await fetch(`${cfg.endpoint}/upload`, { method: 'POST', headers: h, body: form });
    if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`);
    return res.json();
    // Expected response: { success: true, doc_ids: [...], message: "..." }
  },

  // POST /api/generate — generate question sets
  async generate(payload) {
    const cfg = this.getConfig();
    if (!cfg.endpoint) throw new Error('RAG endpoint not configured');
    const res = await fetch(`${cfg.endpoint}/generate`, {
      method: 'POST', headers: this.headers(),
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`Generation failed: HTTP ${res.status}`);
    return res.json();
    /* Expected payload:  { difficulty, count, types, subject, num_sets: 4 }
       Expected response: { sets: [ [questions], [questions], [questions], [questions] ] }
       Each question: { id, q, type, topic, opts?, ans, marks } */
  },

  // POST /api/analyze — analyze student answers
  async analyze(payload) {
    const cfg = this.getConfig();
    if (!cfg.endpoint) throw new Error('RAG endpoint not configured');
    const res = await fetch(`${cfg.endpoint}/analyze`, {
      method: 'POST', headers: this.headers(),
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`Analysis failed: HTTP ${res.status}`);
    return res.json();
    /* Expected payload:  { questions: [...], answers: {...}, student: {...} }
       Expected response: { percentage, earned, total, topicScores, typeScores,
                            strong, canImprove, weak, questionResults, recommendation } */
  }
};

// ── Fallback Question Bank ───────────────────────────────────────────────────
// Fallback disabled - only backend-generated questions are used

// ── Helpers ──────────────────────────────────────────────────────────────────
function getMarks(type) {
  return { MCQ:'1 mark','True/False':'1 mark','Short Answer':'3 marks','Long Answer':'8 marks','Fill in the Blank':'2 marks' }[type] || '1 mark';
}
function getMarksNum(type) {
  return { MCQ:1,'True/False':1,'Short Answer':3,'Long Answer':8,'Fill in the Blank':2 }[type] || 1;
}
function delay(ms) { return new Promise(r => setTimeout(r, ms)); }
function showToast(msg, type = '') {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t?.remove(), 3500);
}
function distributeCounts(total, types) {
  const d = {}; const base = Math.floor(total / types.length); let rem = total - base * types.length;
  types.forEach(t => { d[t] = base; });
  types.forEach(t => { if (rem-- > 0) d[t]++; });
  return d;
}
function seededShuffle(arr, seed) {
  const a = [...arr]; let s = seed + 42;
  for (let i = a.length - 1; i > 0; i--) {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    const j = Math.abs(s) % (i + 1);
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
// Fallback question generation disabled
function localAnalyze(questions, answers) {
  let total = 0, earned = 0;
  const topicScores = {}, typeScores = {}, questionResults = [];
  questions.forEach((q, i) => {
    const m = getMarksNum(q.type);
    total += m;
    const topic = q.topic || 'General';
    const type = q.type;
    if (!topicScores[topic]) topicScores[topic] = { earned: 0, total: 0 };
    if (!typeScores[type]) typeScores[type] = { earned: 0, total: 0 };
    topicScores[topic].total += m;
    typeScores[type].total += m;
    const given = answers[i];
    let e = 0, status = 'wrong';
    if (given === undefined || given === '') { status = 'unanswered'; }
    else if (q.type === 'MCQ') { if (given === q.ans) { e = m; status = 'correct'; } }
    else if (q.type === 'True/False') { if (given === q.ans) { e = m; status = 'correct'; } }
    else {
      const kw = (String(q.ans || '')).toLowerCase().split(/[\s,./]+/).filter(w => w.length > 3);
      const gl = (String(given || '')).toLowerCase();
      const ratio = kw.length > 0 ? kw.filter(k => gl.includes(k)).length / kw.length : 0;
      if (ratio >= 0.6) { e = m; status = 'correct'; }
      else if (ratio >= 0.3) { e = Math.floor(m * 0.5); status = 'partial'; }
    }
    earned += e;
    topicScores[topic].earned += e;
    typeScores[type].earned += e;
    questionResults.push({ q: q.q, type, topic, given, correctAns: q.ans, earned: e, marks: m, status });
  });
  const pct = Math.round((earned / total) * 100);
  const strong = [], canImprove = [], weak = [];
  Object.entries(topicScores).forEach(([t, s]) => {
    const p = s.total > 0 ? Math.round((s.earned / s.total) * 100) : 0;
    if (p >= 70) strong.push({ topic: t, pct: p });
    else if (p >= 40) canImprove.push({ topic: t, pct: p });
    else weak.push({ topic: t, pct: p });
  });
  const avgScore = pct;
  let rec = avgScore >= 75 ? `Excellent performance (${avgScore}%). ` : avgScore >= 50 ? `Good effort (${avgScore}%). ` : `Needs improvement (${avgScore}%). `;
  if (weak.length) rec += `Focus on: ${weak.map(w => w.topic).join(', ')}. `;
  if (canImprove.length) rec += `Can improve: ${canImprove.map(c => c.topic).join(', ')}.`;
  return { percentage: pct, earnedMarks: earned, totalMarks: total, topicScores, typeScores, strong, canImprove, weak, questionResults, pass: pct >= 40, recommendation: rec };
}

// ═══════════════════════════════════════════════════════════════════════════
// INDEX PAGE LOGIC
// ═══════════════════════════════════════════════════════════════════════════
if (document.getElementById('dropZone')) {
  let uploadedFiles = [];
  const FIXED_COUNT = 20;
  let generatedSets = [];
  let currentSetView = 0;

  window.toggleSection = id => {
    const el = document.getElementById(id);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
  };

  // ── Backend config ────────────────────────────────────────────────────────
  function getEndpoint() {
    return 'http://localhost:8000';
  }

  // Initialize RAG config with endpoint
  Store.set('ragConfig', { endpoint: getEndpoint(), apiKey: '' });
  console.log('✅ RAG backend configured:', getEndpoint());

  // ── File Upload ───────────────────────────────────────────────────────────
  const dropZone = document.getElementById('dropZone');
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.closest('.drop-zone').classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.closest('.drop-zone').classList.remove('drag-over'));
  dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.closest('.drop-zone').classList.remove('drag-over'); handleFiles([...e.dataTransfer.files]); });
  document.getElementById('fileInput').addEventListener('change', e => handleFiles([...e.target.files]));

  function handleFiles(files) {
    files.forEach(f => {
      if (uploadedFiles.length >= 10) { showToast('⚠️ Maximum 10 files allowed'); return; }
      if (uploadedFiles.find(x => x.name === f.name)) return;
      uploadedFiles.push(f);
    });
    renderFiles();
  }

  function renderFiles() {
    const grid = document.getElementById('fileGrid');
    grid.innerHTML = uploadedFiles.map((f, i) => `
      <div class="file-card" id="fc${i}">
        <div class="file-card-icon">📄</div>
        <div class="file-card-info">
          <div class="file-card-name">${f.name}</div>
          <div class="file-card-size">${(f.size/1024).toFixed(1)} KB</div>
          <div class="file-card-status">✓ Ready to upload</div>
        </div>
        <button class="file-card-remove" onclick="removeFile(${i})">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>`).join('');
    const pct = (uploadedFiles.length / 10) * 100;
    document.getElementById('uploadBarFill').style.width = pct + '%';
    document.getElementById('fileCount').textContent = uploadedFiles.length;
    document.getElementById('uploadToRAGBtn').style.display = uploadedFiles.length > 0 ? 'inline-flex' : 'none';
    // Show generate button when files have been uploaded to backend
    const hasBackendData = localStorage.getItem('ef_backendChunks') || '0';
    document.getElementById('genBtn').style.display = (parseInt(hasBackendData) > 0) ? 'flex' : 'none';
  }

  window.removeFile = i => { uploadedFiles.splice(i, 1); renderFiles(); };

  window.uploadToRAG = async () => {
    console.log('📤 Upload button clicked');
    console.log('Files ready:', uploadedFiles.length);
    
    const endpoint = getEndpoint();
    console.log('Backend endpoint:', endpoint);
    
    if (!endpoint) { showToast('⚠️ Backend URL not configured'); return; }
    if (uploadedFiles.length === 0) { showToast('⚠️ No files selected'); return; }
    
    const btn = document.getElementById('uploadToRAGBtn');
    btn.disabled = true;
    btn.innerHTML = '⏳ Uploading... (checking backend)';
    
    try {
      // Step 1: Test connectivity
      console.log('1️⃣ Testing backend connectivity...');
      const healthTest = await Promise.race([
        fetch(`${endpoint}/health`),
        new Promise((_, reject) => setTimeout(() => reject(new Error('Health check timeout')), 8000))
      ]);
      
      if (!healthTest.ok) {
        throw new Error(`Backend health check failed: HTTP ${healthTest.status}`);
      }
      console.log('✅ Backend is accessible');
      
      // Step 2: Prepare files
      console.log(`2️⃣ Preparing ${uploadedFiles.length} files for upload...`);
      const form = new FormData();
      uploadedFiles.forEach((f, idx) => {
        console.log(`   File ${idx + 1}: ${f.name} (${(f.size/1024).toFixed(1)} KB)`);
        form.append('files', f);
      });
      
      // Step 3: Upload
      console.log('3️⃣ Sending upload request...');
      btn.innerHTML = '⏳ Uploading files...';
      
      const uploadRes = await Promise.race([
        fetch(`${endpoint}/upload`, {
          method: 'POST',
          body: form
        }),
        new Promise((_, reject) => setTimeout(() => reject(new Error('Upload timeout after 60 seconds')), 60000))
      ]);
      
      console.log('Upload response status:', uploadRes.status);
      
      if (!uploadRes.ok) {
        const errorText = await uploadRes.text();
        console.error('Upload failed response:', errorText);
        throw new Error(`Server error HTTP ${uploadRes.status}: ${errorText.substring(0, 100)}`);
      }
      
      const uploadData = await uploadRes.json();
      console.log('✅ Upload complete:', uploadData);
      
      // Step 4: Verify chunks
      console.log('4️⃣ Verifying chunks in backend...');
      const debugRes = await fetch(`${endpoint}/debug`);
      const debugData = await debugRes.json();
      console.log('📊 Chunks indexed:', debugData.chunks_indexed);
      localStorage.setItem('ef_backendChunks', debugData.chunks_indexed);
      
      if (debugData.chunks_indexed === 0) {
        showToast('⚠️ Files uploaded but no text extracted. Try PDF/DOCX/TXT with readable text.', 'warning');
        console.warn('⚠️ No chunks indexed - files may be unreadable');
        btn.disabled = false;
        btn.innerHTML = '⚠️ Retry with Different Files';
        return;
      }
      
      // Success!
      uploadedFiles.forEach((_, i) => {
        const elem = document.getElementById(`fc${i}`);
        if (elem) elem.classList.add('uploaded');
      });
      
      showToast(`✅ Success! ${debugData.chunks_indexed} chunks indexed. Click "Generate 4 Sets" to proceed.`, 'success');
      document.getElementById('genBtn').style.display = 'flex';
      renderFiles();
    } catch (e) {
      console.error('❌ Upload error:', e.message);
      console.error('Full error:', e);
      
      let friendlyMsg = e.message;
      if (e.message.includes('Failed to fetch')) {
        friendlyMsg = '❌ Cannot reach backend. Is the Jupyter notebook running? http://localhost:8000 should be accessible.';
      } else if (e.message.includes('timeout')) {
        friendlyMsg = '❌ Upload timed out. Files may be too large or network is slow.';
      } else if (e.message.includes('HTTP')) {
        friendlyMsg = `❌ Server error: ${e.message}`;
      }
      
      showToast(friendlyMsg, 'error');
      console.log('✓ Check browser console (F12) for more details');
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Send to Backend`;
    }
  };

  // ── Slider ────────────────────────────────────────────────────────────────
  // (removed — question count is fixed at 10)

  // ── Difficulty ────────────────────────────────────────────────────────────
  // (removed — difficulty is fixed at medium)

  function getTypes() {
    const map = { MCQ:'t_mcq','Short Answer':'t_short','Long Answer':'t_long','True/False':'t_tf','Fill in the Blank':'t_fill' };
    return Object.entries(map).filter(([,id]) => document.getElementById(id)?.checked).map(([t]) => t);
  }

  // ── Generate ──────────────────────────────────────────────────────────────
  window.generatePapers = async () => {
    const types = ['MCQ'];
    const count = FIXED_COUNT;
    const difficulty = 'medium';
    const subject = 'General Subject';
    const btn = document.getElementById('genBtn');
    btn.disabled = true;
    document.getElementById('genProgress').style.display = 'block';
    document.getElementById('setsOutput').style.display = 'none';

    const steps = ['Initializing RAG pipeline...','Retrieving relevant chunks...','Extracting question patterns...','Generating Set A...','Generating Set B...','Generating Set C...','Generating Set D...','Applying difficulty calibration...','Deduplicating questions...','Finalizing paper sets...'];
    const stepsEl = document.getElementById('genSteps');
    stepsEl.innerHTML = steps.map((s, i) => `<span class="gen-step" id="gs${i}">${s}</span>`).join('');

    async function tick(i, pct) {
      await delay(380);
      document.getElementById(`gs${i}`)?.classList.add('active');
      document.getElementById('genBarFill').style.width = pct + '%';
      document.getElementById('genBarLabel').textContent = steps[i];
      if (i > 0) document.getElementById(`gs${i-1}`)?.classList.replace('active','done');
    }

    for (let i = 0; i < steps.length; i++) await tick(i, ((i+1)/steps.length)*100);

    try {
      const endpoint = getEndpoint();
      if (!endpoint) throw new Error('Backend URL not configured');
      
      // Health check
      try {
        const healthRes = await fetch(`${endpoint}/health`);
        if (!healthRes.ok) throw new Error('Backend not responding');
        console.log('✅ Backend is alive');
      } catch (e) {
        throw new Error(`Backend unreachable at ${endpoint}. Is the server running?`);
      }
      
      // Check if chunks are indexed
      const debugRes = await fetch(`${endpoint}/debug`);
      const debugData = await debugRes.json();
      console.log('📊 Chunks available:', debugData.chunks_indexed);
      
      if (debugData.chunks_indexed === 0) {
        throw new Error('❌ No documents indexed. Please upload and send exam papers to the backend first.');
      }
      
      console.log('🔄 Calling /generate endpoint...');
      const res = await fetch(`${endpoint}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ difficulty, count, types, subject, num_sets: 4 })
      });
      
      if (!res.ok) {
        const err = await res.text();
        throw new Error(`Backend error (${res.status}): ${err}`);
      }
      const data = await res.json();
      if (!data.sets || !data.sets.length) throw new Error('Empty response from backend');
      generatedSets = data.sets;
      showToast('✅ Generated 4 paper sets from your uploaded papers!', 'success');
    } catch (e) {
      console.error('❌ Generation error:', e);
      showToast(`❌ ${e.message}`, 'error');
      generatedSets = [];
    }


    const config = { difficulty, count, types, subject, sets: generatedSets };
    Store.set('examConfig', config);

    btn.disabled = false;
    document.getElementById('genProgress').style.display = 'none';
    
    // Check if any sets have questions
    const totalQuestions = generatedSets.reduce((sum, set) => sum + (set ? set.length : 0), 0);
    if (totalQuestions === 0) {
      showToast('❌ No questions generated. Try uploading different papers.', 'error');
      console.error('❌ All sets are empty:', generatedSets);
      return;
    }
    
    document.getElementById('setsOutput').style.display = 'block';
    ['A','B','C','D'].forEach((l,i) => {
      const count = generatedSets[i]?.length || 0;
      document.getElementById(`tabCount${i}`).textContent = count > 0 ? `${count} Qs` : 'Empty';
    });
    
    // Show first non-empty set
    let firstSet = 0;
    for (let i = 0; i < generatedSets.length; i++) {
      if (generatedSets[i] && generatedSets[i].length > 0) {
        firstSet = i;
        break;
      }
    }
    showSet(firstSet);
    document.getElementById('setsOutput').scrollIntoView({ behavior:'smooth' });
    console.log('✅ Sets generated successfully:', generatedSets.map((s,i) => `Set ${['A','B','C','D'][i]}: ${s?.length || 0} questions`).join(', '));
  };

  window.showSet = i => {
    currentSetView = i;
    document.querySelectorAll('.set-tab').forEach((t,idx) => t.classList.toggle('active', idx === i));
    const config = Store.get('examConfig');
    if (!config) return;
    renderPreview(config.sets[i], i, config);
  };

  function renderPreview(questions, setIdx, config) {
    const L = ['A','B','C','D'];
    const types = [...new Set(questions.map(q => q.type))];
    let html = `<div class="preview-paper-title">
      <h3>${config.subject} — Set ${L[setIdx]}</h3>
      <p>Difficulty: ${config.difficulty.charAt(0).toUpperCase()+config.difficulty.slice(1)} &nbsp;|&nbsp; ${questions.length} Questions &nbsp;|&nbsp; Total Marks: ${questions.reduce((s,q)=>s+getMarksNum(q.type),0)}</p>
    </div>
    <div class="preview-meta-row">
      <span>Set: ${L[setIdx]}</span>
      <span>Types: ${config.types.join(', ')}</span>
      <span>Date: ${new Date().toLocaleDateString('en-IN')}</span>
    </div>`;
    let n = 1;
    types.forEach((type, ti) => {
      const qs = questions.filter(q => q.type === type);
      html += `<div class="preview-section-head">Section ${String.fromCharCode(65+ti)} — ${type} (${getMarks(type)} each)</div>`;
      qs.forEach(q => {
        html += `<div class="preview-q-row">
          <div class="preview-q-num">${n++}</div>
          <div class="preview-q-body">${q.q}
            ${q.type==='MCQ'?`<div class="preview-opts">${q.opts.map((o,i)=>`<div class="preview-opt">${['A','B','C','D'][i]}) ${o}</div>`).join('')}</div>`:''}
            ${q.type==='True/False'?`<div style="font-size:0.75rem;color:var(--muted);margin-top:4px">[ True / False ]</div>`:''}
            ${q.type==='Fill in the Blank'?`<div style="font-size:0.75rem;color:var(--muted);margin-top:4px">Answer: ___________</div>`:''}
          </div>
          <div class="preview-marks">${getMarks(type)}</div>
        </div>`;
      });
    });
    document.getElementById('paperPreview').innerHTML = html;
  }

  window.downloadAll = () => {
    const config = Store.get('examConfig');
    if (!config) return;
    const L = ['A','B','C','D'];
    config.sets.forEach((set, i) => {
      let txt = `${config.subject} — Set ${L[i]}\nDifficulty: ${config.difficulty}\n${'─'.repeat(50)}\n\n`;
      set.forEach((q, idx) => {
        txt += `${idx+1}. [${q.type}] ${q.q}\n`;
        if (q.type==='MCQ') q.opts.forEach((o,oi)=>{ txt+=`   ${['A','B','C','D'][oi]}) ${o}\n`; });
        txt += '\n';
      });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([txt],{type:'text/plain'}));
      a.download = `Set_${L[i]}_${config.subject.replace(/\s+/g,'_')}.txt`;
      a.click();
    });
    showToast('⬇️ Downloading all 4 sets...');
  };
}
