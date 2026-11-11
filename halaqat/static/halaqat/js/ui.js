/* أدوات واجهة عامة: تبويبات فرعية + قوائم منسدلة متعددة الاختيار + فلترة/تقسيم الجداول */
(function () {
  // ── التبويبات الفرعية: <div data-subtabs> … <section class="subpane" data-tab="x" data-title="…"> ──
  document.querySelectorAll('[data-subtabs]').forEach(root => {
    const panes = [...root.querySelectorAll(':scope > .subpane')];
    if (!panes.length) return;
    const bar = document.createElement('div');
    bar.className = 'subtabs';
    const key = 'subtab:' + location.pathname;
    const show = id => {
      panes.forEach(p => { p.hidden = p.dataset.tab !== id; });
      bar.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.tab === id));
      try { sessionStorage.setItem(key, id); } catch (e) {}
      if (history.replaceState) history.replaceState(null, '', '#' + id);
    };
    panes.forEach(p => {
      const b = document.createElement('button');
      b.type = 'button'; b.dataset.tab = p.dataset.tab; b.textContent = p.dataset.title;
      b.onclick = () => show(p.dataset.tab);
      bar.appendChild(b);
    });
    root.prepend(bar);
    let start = location.hash.slice(1);
    // تبويبة فيها أخطاء نموذج تُفتح تلقائياً
    const err = panes.find(p => p.querySelector('.form-errors, .errorlist'));
    if (err) start = err.dataset.tab;
    if (!panes.some(p => p.dataset.tab === start)) {
      try { start = sessionStorage.getItem(key); } catch (e) { start = null; }
    }
    if (!panes.some(p => p.dataset.tab === start)) start = panes[0].dataset.tab;
    show(start);
  });

  // ── القوائم المنسدلة متعددة الاختيار ──
  document.querySelectorAll('.dd-multi').forEach(dd => {
    const lbl = dd.querySelector('.dd-label');
    const boxes = [...dd.querySelectorAll('input[type=checkbox]')];
    const update = () => {
      const names = boxes.filter(b => b.checked).map(b => b.parentElement.textContent.trim());
      lbl.textContent = names.length ? names.join('، ') : lbl.dataset.empty;
    };
    boxes.forEach(b => b.addEventListener('change', update));
    update();
    const q = dd.querySelector('.dd-search');
    if (q) q.addEventListener('input', () => {
      const v = q.value.trim();
      boxes.forEach(b => { b.parentElement.style.display = !v || b.parentElement.textContent.includes(v) ? '' : 'none'; });
    });
    document.addEventListener('click', e => { if (!dd.contains(e.target)) dd.open = false; });
  });

  // ── جداول: <table data-pager="20"> بحث عام واحد + صفحات ──
  document.querySelectorAll('table[data-pager]').forEach(tbl => {
    const size = parseInt(tbl.dataset.pager, 10) || 20;
    const rows = [...tbl.tBodies[0].rows];
    if (rows.length <= size && !tbl.hasAttribute('data-search')) return;
    const wrap = tbl.closest('.table-scroll') || tbl;
    const tools = document.createElement('div');
    tools.className = 'tbl-tools';
    tools.innerHTML = '<input type="search" placeholder="🔍 فلترة الجدول…">';
    wrap.before(tools);
    const pager = document.createElement('div');
    pager.className = 'tbl-pager';
    wrap.after(pager);
    let page = 0, list = rows;
    const input = tools.querySelector('input');
    const norm = s => (window.StudentIndex ? StudentIndex.norm(s) : s.toLowerCase());
    const texts = rows.map(r => norm(r.textContent));
    const render = () => {
      const pages = Math.max(1, Math.ceil(list.length / size));
      page = Math.min(page, pages - 1);
      rows.forEach(r => { r.style.display = 'none'; });
      list.slice(page * size, page * size + size).forEach(r => { r.style.display = ''; });
      pager.innerHTML = '';
      if (pages > 1) {
        const mk = (t, p, on, dis) => {
          const b = document.createElement('button'); b.type = 'button'; b.textContent = t;
          if (on) b.className = 'on'; if (dis) b.disabled = true;
          b.onclick = () => { page = p; render(); }; pager.appendChild(b);
        };
        mk('‹ السابق', page - 1, false, page === 0);
        for (let i = 0; i < pages; i++) {
          if (i === 0 || i === pages - 1 || Math.abs(i - page) <= 2) mk(String(i + 1), i, i === page);
          else if (Math.abs(i - page) === 3) { const s = document.createElement('span'); s.textContent = '…'; pager.appendChild(s); }
        }
        mk('التالي ›', page + 1, false, page === pages - 1);
      }
      const info = document.createElement('span');
      info.style.marginInlineStart = '8px';
      info.textContent = `${list.length} صف`;
      pager.appendChild(info);
    };
    input.addEventListener('input', () => {
      const v = norm(input.value.trim());
      list = v ? rows.filter((r, i) => texts[i].includes(v)) : rows;
      page = 0; render();
    });
    render();
  });
})();
