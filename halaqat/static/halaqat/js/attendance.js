// حفظ تلقائي لحالة الحضور فور الضغط على الخيار - بدون زر حفظ
// يعمل بشكل عام على أي صف يحمل data-save-url / data-kind / data-entity-id / data-date
// (صفحة تفاصيل الحلقة وصفحة الغائبين كلتاهما تستخدم نفس الآلية)
document.addEventListener('DOMContentLoaded', function () {
  const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
  const toast = document.getElementById('save-toast');
  if (!csrfInput) return;
  const csrfToken = csrfInput.value;

  let toastTimer = null;
  function showToast(ok, msg) {
    if (!toast) return;
    toast.textContent = msg || (ok ? 'تم الحفظ ✓' : 'تعذّر الحفظ، حاول مجدداً');
    toast.classList.toggle('error', !ok);
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 1600);
  }

  function updateCounts(counts) {
    const p = document.getElementById('cnt-present');
    const a = document.getElementById('cnt-absent');
    const e = document.getElementById('cnt-excused');
    if (p) p.textContent = counts.present;
    if (a) a.textContent = counts.absent;
    if (e) e.textContent = counts.excused;
  }

  document.body.addEventListener('change', function (e) {
    const input = e.target;
    if (input.type !== 'radio') return;

    const row = input.closest('[data-save-url]');
    if (!row) return;

    const { saveUrl, kind, entityId, date } = row.dataset;
    const status = input.value;

    row.classList.add('saving');

    const formData = new URLSearchParams();
    formData.append('kind', kind || 'student');
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
          if (data.counts) updateCounts(data.counts);
          showToast(true);

          // في صفحة الغائبين: إن تغيّرت حالة طالب من "غائب/إذن" لحالة أخرى، أخفِ صفه تلقائياً
          if (row.classList.contains('resolvable-row')) {
            const originalStatus = row.dataset.originalStatus;
            if (status !== originalStatus) {
              row.classList.add('resolved');
              setTimeout(() => {
                row.remove();
              }, 450);
            }
          }
        } else {
          showToast(false, data.error || 'تعذّر الحفظ');
        }
      })
      .catch(() => {
        row.classList.remove('saving');
        showToast(false);
      });
  });
});
