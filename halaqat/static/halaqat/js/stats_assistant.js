/*
 * المساعد الإحصائي: سؤال بالعربية ⇒ مواصفة منظّمة ⇒ جدول، مع تعديل التفسير يدوياً وتصدير Excel / PDF.
 * الخادم هو من يحوّل السؤال (ask) وينفّذ المواصفة (run)؛ الواجهة تعرض فقط وتبني نموذج التعديل من القوائم المسموحة (META).
 * تعتمد على getCsrf / showToast / setBtnLoading (base.html).
 */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const root = $('ai-root');
  if (!root) return;
  const META = JSON.parse($('ai-meta-data').textContent);
  const HISTORY = JSON.parse($('ai-history-data').textContent);
  const URLS = {ask: root.dataset.ask, run: root.dataset.run, xlsx: root.dataset.xlsx, pdf: root.dataset.pdf};
  const AI_ON = root.dataset.ai === '1';
  const DEFAULT_METRICS = ['rate', 'present', 'late', 'absent', 'excused'];
  const toast = (m, t) => { if (typeof window.showToast === 'function') window.showToast(m, t || 'info', 3500); };

  let currentSpec = null;      // آخر مواصفة منظَّفة عادت من الخادم (هي ما يُصدَّر)
  let conds = [];              // صفوف الشروط في النموذج
  let metricOrder = [];        // ترتيب الأعمدة كما جاء في المواصفة (لتبقى كما هي عند التعديل)
  let tbl = {result: null, rows: [], col: -1, dir: 1};

  /* ───────── الاتصال بالخادم ───────── */
  async function post(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: {'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest'},
      body: new URLSearchParams(body),
    });
    const data = await res.json().catch(() => ({ok: false, error: 'استجابة غير صالحة من الخادم'}));
    return data;
  }

  /* ───────── نموذج التعديل ───────── */
  $('f-subject').innerHTML = META.subjects.map(s => `<option value="${s.key}">${esc(s.label)}</option>`).join('');
  $('f-group').innerHTML = META.groups.map(g => `<option value="${g.key}">${esc(g.label)}</option>`).join('');
  $('f-circles').innerHTML = META.circles.map(c => `<label class="ai-check"><input type="checkbox" value="${c.id}"> ${esc(c.name)}</label>`).join('')
    || '<span class="ai-meta">لا توجد حلقات</span>';

  const allowedMetrics = (subject, group) => META.metrics[subject].filter(m => !(m.key === 'people' && group === 'person'));

  function renderMetrics(selected) {
    const subject = $('f-subject').value, group = $('f-group').value;
    const list = allowedMetrics(subject, group);
    const keys = list.map(m => m.key);
    let keep = (selected || []).filter(k => keys.includes(k));
    if (!keep.length) keep = list.filter(m => DEFAULT_METRICS.includes(m.key)).map(m => m.key);
    $('f-metrics').innerHTML = list.map(m =>
      `<label class="ai-check"><input type="checkbox" value="${m.key}"${keep.includes(m.key) ? ' checked' : ''}> ${esc(m.label)}</label>`).join('');
    const prevSort = $('f-sort').value;
    const sortOpts = list.map(m => ({key: m.key, label: m.label})).concat([{key: 'name', label: 'الاسم'}], group === 'month' ? [{key: 'month', label: 'الشهر'}] : []);
    $('f-sort').innerHTML = sortOpts.map(o => `<option value="${o.key}">${esc(o.label)}</option>`).join('');
    if (sortOpts.some(o => o.key === prevSort)) $('f-sort').value = prevSort;
    conds = conds.filter(c => keys.includes(c.metric));
    renderConds();
  }

  function renderConds() {
    const list = allowedMetrics($('f-subject').value, $('f-group').value);
    $('f-conds').innerHTML = conds.map((c, i) => `
      <div class="ai-cond" data-i="${i}">
        <select data-k="metric">${list.map(m => `<option value="${m.key}"${m.key === c.metric ? ' selected' : ''}>${esc(m.label)}</option>`).join('')}</select>
        <select data-k="op">${META.ops.map(o => `<option value="${o.key}"${o.key === c.op ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>
        <input type="number" data-k="value" value="${esc(c.value)}" step="any" inputmode="decimal" aria-label="القيمة">
        <button type="button" class="qs-btn" data-del aria-label="حذف الشرط">✕</button>
      </div>`).join('');
    $('f-addcond').hidden = conds.length >= META.max_conditions;
  }

  function toggleVisibility() {
    const students = $('f-subject').value === 'students', person = $('f-group').value === 'person';
    $('f-circles-wrap').hidden = !students;
    $('f-person-wrap').querySelectorAll('label:nth-child(n+2)').forEach(l => { l.hidden = !students; });   // العمر للطلاب فقط
    $('f-monthly-wrap').hidden = !person;
  }

  function fillForm(s) {
    $('f-subject').value = s.subject;
    $('f-group').value = s.group_by;
    conds = (s.conditions || []).map(c => ({metric: c.metric, op: c.op, value: c.value}));
    metricOrder = (s.metrics || []).slice();
    $('f-sort').innerHTML = '';
    renderMetrics(s.metrics);
    $('f-from').value = s.date_from || '';
    $('f-to').value = s.date_to || '';
    const wanted = new Set((s.circles || []).map(String));
    $('f-circles').querySelectorAll('input').forEach(i => { i.checked = wanted.has(i.value); });
    $('f-name').value = s.name_contains || '';
    $('f-agemin').value = s.age_min == null ? '' : s.age_min;
    $('f-agemax').value = s.age_max == null ? '' : s.age_max;
    $('f-monthly').checked = !!s.monthly_columns;
    $('f-sort').value = s.sort_by;
    $('f-dir').value = s.sort_dir;
    $('f-limit').value = s.limit;
    toggleVisibility();
  }

  function readForm() {
    const subject = $('f-subject').value, group = $('f-group').value;
    const num = id => { const v = $(id).value.trim(); return v === '' || isNaN(Number(v)) ? null : Number(v); };
    return {
      subject, group_by: group,
      metrics: [...$('f-metrics').querySelectorAll('input:checked')].map(i => i.value)
        .sort((a, b) => ((metricOrder.indexOf(a) + 1) || 999) - ((metricOrder.indexOf(b) + 1) || 999)),   // ترتيب المواصفة أولاً
      date_from: $('f-from').value || null, date_to: $('f-to').value || null,
      circles: subject === 'students' ? [...$('f-circles').querySelectorAll('input:checked')].map(i => Number(i.value)) : [],
      name_contains: $('f-name').value.trim(),
      age_min: subject === 'students' ? num('f-agemin') : null, age_max: subject === 'students' ? num('f-agemax') : null,
      monthly_columns: $('f-monthly').checked && group === 'person',
      conditions: conds.filter(c => c.value !== '' && c.value != null && !isNaN(Number(c.value))).map(c => ({metric: c.metric, op: c.op, value: Number(c.value)})),
      sort_by: $('f-sort').value, sort_dir: $('f-dir').value, limit: num('f-limit') || 50,
    };
  }

  const defaultSpec = () => ({subject: 'students', group_by: 'person', metrics: DEFAULT_METRICS.slice(), date_from: null, date_to: null,
    circles: [], name_contains: '', age_min: null, age_max: null, monthly_columns: false, conditions: [],
    sort_by: 'rate', sort_dir: 'desc', limit: 50});

  ['f-subject', 'f-group'].forEach(id => $(id).addEventListener('change', () => {
    renderMetrics(readForm().metrics);
    toggleVisibility();
  }));
  $('f-addcond').addEventListener('click', () => {
    const list = allowedMetrics($('f-subject').value, $('f-group').value);
    conds.push({metric: (list.find(m => m.key === 'absent') || list[0]).key, op: '>=', value: ''});
    renderConds();
  });
  $('f-conds').addEventListener('change', e => {
    const row = e.target.closest('.ai-cond');
    if (row && e.target.dataset.k) conds[+row.dataset.i][e.target.dataset.k] = e.target.value;
  });
  $('f-conds').addEventListener('input', e => {
    const row = e.target.closest('.ai-cond');
    if (row && e.target.dataset.k === 'value') conds[+row.dataset.i].value = e.target.value;
  });
  $('f-conds').addEventListener('click', e => {
    if (!e.target.closest('[data-del]')) return;
    conds.splice(+e.target.closest('.ai-cond').dataset.i, 1);
    renderConds();
  });

  /* ───────── عرض النتيجة ───────── */
  function cellHtml(c, v, summary) {
    if (c.kind === 'text') return `<td class="t">${esc(v == null ? '—' : v)}</td>`;
    if (v == null) return '<td class="st-none">—</td>';
    if (c.kind === 'pct') {
      const cls = summary ? '' : (v >= 85 ? 'rate-good' : v >= 65 ? 'rate-mid' : 'rate-bad');
      return `<td class="${cls}">${esc(v)}%</td>`;
    }
    return `<td>${esc(v)}</td>`;
  }

  function drawTable() {
    const res = tbl.result, cols = res.columns;
    const head = cols.map((c, i) => `<th data-i="${i}" class="${tbl.col === i ? (tbl.dir > 0 ? 'asc' : 'desc') : ''}">${esc(c.label)}</th>`).join('');
    const body = tbl.rows.map(r => '<tr>' + r.map((v, i) => cellHtml(cols[i], v, false)).join('') + '</tr>').join('')
      || `<tr><td colspan="${cols.length}" class="ai-empty">لا توجد نتائج مطابقة — خفّف الشروط أو وسّع الفترة.</td></tr>`;
    const foot = res.summary ? '<tfoot><tr class="total">' + res.summary.map((v, i) => cellHtml(cols[i], v, true)).join('') + '</tr></tfoot>' : '';
    $('ai-table').innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>${foot}`;
  }

  $('ai-table').addEventListener('click', e => {           // فرز بالنقر على ترويسة العمود (في الصفحة فقط)
    const th = e.target.closest('th[data-i]');
    if (!th || !tbl.result) return;
    const i = +th.dataset.i, kind = tbl.result.columns[i].kind;
    tbl.dir = tbl.col === i ? -tbl.dir : (kind === 'text' ? 1 : -1);
    tbl.col = i;
    const withVal = tbl.rows.filter(r => r[i] != null), without = tbl.rows.filter(r => r[i] == null);
    withVal.sort((a, b) => (kind === 'text' ? String(a[i]).localeCompare(String(b[i]), 'ar') : a[i] - b[i]) * tbl.dir);
    tbl.rows = withVal.concat(without);
    drawTable();
  });

  function showResult(data) {
    currentSpec = data.spec;
    fillForm(data.spec);
    const res = data.result;
    tbl = {result: res, rows: res.rows.slice(), col: -1, dir: 1};
    $('ai-work').hidden = false;
    $('ai-understood-box').hidden = false;
    $('ai-understood').textContent = res.understood;
    $('ai-warnings').innerHTML = (data.warnings || []).map(w => `<div class="ai-warn">⚠️ ${esc(w)}</div>`).join('');
    $('ai-title').textContent = res.title;
    $('ai-meta').textContent = `${res.row_count} صفاً${res.truncated ? ' (المعروض أول ' + res.rows.length + ')' : ''} · الفترة ${res.period[0]} ← ${res.period[1]}`;
    $('ai-notes').innerHTML = (res.notes || []).map(n => `<div>• ${esc(n)}</div>`).join('');
    $('ai-result').hidden = false;
    drawTable();
  }

  function showError(msg) {
    const box = $('ai-error');
    box.textContent = '⚠️ ' + msg;
    box.hidden = false;
  }
  const clearError = () => { $('ai-error').hidden = true; };

  /* ───────── سجل الأسئلة ───────── */
  function renderHistory() {
    $('ai-history-box').hidden = HISTORY.length === 0;
    $('ai-history').innerHTML = HISTORY.map((h, i) => `
      <button type="button" class="ai-hist" data-i="${i}">
        <span class="ai-hist-q">${h.question ? esc(h.question) : '⚙️ استعلام يدوي'}</span>
        <span class="ai-hist-t">${esc(h.when)}</span>
      </button>`).join('');
  }
  $('ai-history').addEventListener('click', e => {
    const b = e.target.closest('.ai-hist');
    if (!b) return;
    let spec;
    try { spec = JSON.parse(HISTORY[+b.dataset.i].spec); } catch (err) { return; }
    runSpec(spec);                                          // بلا استدعاء للذكاء الاصطناعي (مجاني وفوري)
  });
  function remember(question, spec) {
    const json = JSON.stringify(spec);
    if (HISTORY[0] && HISTORY[0].spec === json && HISTORY[0].question === question) return;     // لا نكرّر نفس الإدخال
    const d = new Date(), p = n => String(n).padStart(2, '0');
    HISTORY.unshift({question, spec: json, via: question ? 'ai' : 'manual', ok: true,
                     when: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`});
    HISTORY.length = Math.min(HISTORY.length, 12);
    renderHistory();
  }

  /* ───────── الأوامر ───────── */
  async function runSpec(spec, btn) {
    clearError();
    if (btn) setBtnLoading(btn, true);
    try {
      const data = await post(URLS.run, {spec: JSON.stringify(spec)});
      if (!data.ok) { showError(data.error || 'تعذّر التنفيذ'); return; }
      showResult(data);
      remember('', data.spec);
      $('ai-result').scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (e) {
      showError('تعذّر الاتصال بالخادم');
    } finally {
      if (btn) setBtnLoading(btn, false);
    }
  }

  async function ask(question) {
    question = (question || '').trim();
    if (!question) { toast('⚠️ اكتب سؤالك أولاً', 'warn'); return; }
    clearError();
    const btn = $('ai-go');
    setBtnLoading(btn, true);
    try {
      const data = await post(URLS.ask, {question});
      if (!data.ok) {
        showError(data.error || 'تعذّر فهم السؤال');
        if (data.code === 'no_key' || data.code === 'rate') openManual();
        return;
      }
      showResult(data);
      remember(question, data.spec);
      $('ai-understood-box').scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (e) {
      showError('تعذّر الاتصال بالخادم');
    } finally {
      setBtnLoading(btn, false);
    }
  }

  function openManual() {
    if (!currentSpec) fillForm(defaultSpec());
    $('ai-work').hidden = false;
    $('ai-edit').open = true;
    $('ai-edit').scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function exportAs(fmt) {
    if (!currentSpec) return;
    const f = document.createElement('form');
    f.method = 'post';
    f.action = URLS[fmt];
    f.style.display = 'none';
    [['csrfmiddlewaretoken', getCsrf()], ['spec', JSON.stringify(currentSpec)]].forEach(([k, v]) => {
      const i = document.createElement('input');
      i.type = 'hidden'; i.name = k; i.value = v;
      f.appendChild(i);
    });
    document.body.appendChild(f);
    f.submit();
    setTimeout(() => f.remove(), 1500);
    toast('⏳ جاري تجهيز الملف…', 'info');
  }

  /* ───────── ربط الأحداث ───────── */
  $('ai-go').addEventListener('click', () => ask($('ai-q').value));
  $('ai-q').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask($('ai-q').value); } });
  document.querySelectorAll('.ai-chip').forEach(b => b.addEventListener('click', () => { $('ai-q').value = b.dataset.q; ask(b.dataset.q); }));
  $('ai-manual').addEventListener('click', openManual);
  $('f-run').addEventListener('click', () => runSpec(readForm(), $('f-run')));
  $('ai-xlsx').addEventListener('click', () => exportAs('xlsx'));
  $('ai-pdf').addEventListener('click', () => exportAs('pdf'));

  fillForm(defaultSpec());
  renderHistory();
})();
