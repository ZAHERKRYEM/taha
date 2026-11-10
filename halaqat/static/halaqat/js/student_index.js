/*
 * فهرس أسماء الطلاب المخزَّن محلياً في المتصفح (localStorage).
 * يُحمَّل مرة واحدة من /students/index.json ثم يتم كل البحث داخل المتصفح بلا طلبات للسيرفر.
 * عند كل فتح صفحة يُرسَل طلب صغير بالنسخة الحالية (?v=...)، ولا تُعاد القائمة كاملةً إلا إن تغيّرت.
 *
 * الاستخدام: StudentIndex.search('محمد', 15).then(results => ...)
 * كل نتيجة: {id, name, circle_id, circle_name}
 */
(function () {
  const KEY = 'taha_students_index_v1';
  const URL = '/students/index.json';
  let data = null;          // {v, students: [[id, name, circle_id, circle_name], ...]}
  let refreshing = null;

  // توحيد الحروف العربية: أ/إ/آ→ا، ى→ي، ة→ه، حذف التشكيل والتطويل
  function norm(s) {
    return String(s || '')
      .replace(/[ً-ْٰـ]/g, '')
      .replace(/[أإآٱ]/g, 'ا').replace(/ى/g, 'ي').replace(/ة/g, 'ه')
      .replace(/ؤ/g, 'و').replace(/ئ/g, 'ي')
      .replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function load() {
    try { const raw = localStorage.getItem(KEY); if (raw) data = JSON.parse(raw); } catch (e) { data = null; }
    if (data && data.students) data.students.forEach(r => { r[4] = norm(r[1]); });
  }

  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify({v: data.v, students: data.students.map(r => r.slice(0, 4))}));
    } catch (e) { /* مساحة ممتلئة أو وضع خاص — نكتفي بالذاكرة */ }
  }

  function refresh() {
    if (refreshing) return refreshing;
    const v = data && data.v ? '?v=' + encodeURIComponent(data.v) : '';
    refreshing = fetch(URL + v, {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin'})
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(j => {
        if (!j.same && j.students) {
          j.students.forEach(r => { r[4] = norm(r[1]); });
          data = j; save();
        }
        return data;
      })
      .catch(() => data)
      .finally(() => { setTimeout(() => { refreshing = null; }, 30000); });
    return refreshing;
  }

  function ready() {
    if (data && data.students) { refresh(); return Promise.resolve(data); }   // تحديث بالخلفية
    return refresh();
  }

  function search(q, limit) {
    limit = limit || 15;
    const nq = norm(q);
    if (!nq) return Promise.resolve([]);
    const words = nq.split(' ');
    return ready().then(d => {
      if (!d || !d.students) return [];
      const out = [];
      for (const r of d.students) {
        const n = r[4];
        if (words.every(w => n.includes(w))) {
          out.push({id: r[0], name: r[1], circle_id: r[2], circle_name: r[3], _start: n.startsWith(nq) ? 0 : 1});
        }
      }
      out.sort((a, b) => a._start - b._start || a.name.localeCompare(b.name, 'ar'));
      return out.slice(0, limit);
    });
  }

  function clear() { try { localStorage.removeItem(KEY); } catch (e) {} data = null; }

  load();
  window.StudentIndex = {search, refresh, clear, norm, count: () => (data && data.students ? data.students.length : 0)};
  // تجهيز الفهرس مبكراً حتى يكون البحث فورياً
  if (document.readyState !== 'loading') ready(); else document.addEventListener('DOMContentLoaded', ready);
})();
