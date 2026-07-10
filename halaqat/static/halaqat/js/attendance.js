// حفظ تلقائي لحالة الحضور (طالب أو أستاذ) فور الضغط على الخيار - بدون زر حفظ
document.addEventListener('DOMContentLoaded', function () {
  const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
  const toast = document.getElementById('save-toast');
  if (!csrfInput) return;
  const csrfToken = csrfInput.value;

  let toastTimer = null;
  function showToast(ok) {
    if (!toast) return;
    toast.textContent = ok ? 'تم الحفظ ✓' : 'تعذّر الحفظ، حاول مجدداً';
    toast.classList.toggle('error', !ok);
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 1600);
  }

  function updateCounts(counts) {
    if (!counts) return;
    const p = document.getElementById('cnt-present');
    const a = document.getElementById('cnt-absent');
    const x = document.getElementById('cnt-excused');
    if (p) p.textContent = counts.present;
    if (a) a.textContent = counts.absent;
    if (x) x.textContent = counts.excused;
  }

  // نستمع على مستوى الصفحة كلها عشان يشتغل مع صف الأستاذ (#teacherBox) وصفوف الطلاب (#studentTable) مع بعض
  document.addEventListener('change', function (e) {
    const input = e.target;
    if (input.type !== 'radio') return;

    const row = input.closest('.student-row');
    if (!row) return;

    // كل صف (طالب أو أستاذ) موجود جوه container عليه data-save-url و data-date
    const container = row.closest('[data-save-url]');
    if (!container) return;

    const saveUrl = container.dataset.saveUrl;
    const date = container.dataset.date;
    const kind = row.dataset.kind || 'student';
    const entityId = row.dataset.entityId;
    const status = input.value;

    row.classList.add('saving');

    const formData = new URLSearchParams();
    formData.append('kind', kind);
    formData.append('entity_id', entityId);
    formData.append('status', status);
    formData.append('date', date);

    fetch(saveUrl, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: formData.toString(),
    })
      .then((res) => res.json())
      .then((data) => {
        row.classList.remove('saving');
        if (data.ok) {
          updateCounts(data.counts);
          showToast(true);
        } else {
          showToast(false);
        }
      })
      .catch(() => {
        row.classList.remove('saving');
        showToast(false);
      });
  });
});