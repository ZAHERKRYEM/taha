// حفظ تلقائي لحالة الحضور فور الضغط على الخيار - بدون زر حفظ
document.addEventListener('DOMContentLoaded', function () {
  const table = document.getElementById('studentTable');
  if (!table) return;

  const circleId = table.dataset.circleId;
  const date = table.dataset.date;
  const saveUrl = table.dataset.saveUrl;
  const csrfToken = document.querySelector('input[name="csrfmiddlewaretoken"]').value;
  const toast = document.getElementById('save-toast');

  let toastTimer = null;
  function showToast(ok) {
    toast.textContent = ok ? 'تم الحفظ ✓' : 'تعذّر الحفظ، حاول مجدداً';
    toast.classList.toggle('error', !ok);
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 1600);
  }

  function updateCounts(counts) {
    document.getElementById('cnt-present').textContent = counts.present;
    document.getElementById('cnt-absent').textContent = counts.absent;
    document.getElementById('cnt-excused').textContent = counts.excused;
  }

  table.addEventListener('change', function (e) {
    const input = e.target;
    if (input.type !== 'radio') return;

    const row = input.closest('.student-row');
    const studentId = row.dataset.studentId;
    const status = input.value;

    row.classList.add('saving');

    const formData = new URLSearchParams();
    formData.append('student_id', studentId);
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
