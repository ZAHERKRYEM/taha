// بحث فوري عن طالب بالاسم - يعرض اسمه وحلقته، والضغط عليه ينقل لصفحة تلك الحلقة
document.addEventListener('DOMContentLoaded', function () {
  const input = document.getElementById('studentSearch');
  const results = document.getElementById('searchResults');
  if (!input || !results) return;

  const searchUrl = input.dataset.searchUrl || '/search-students/';
  let debounceTimer = null;
  let lastQuery = '';

  function render(items) {
    if (!items.length) {
      results.innerHTML = '<div class="no-result">لا توجد نتائج مطابقة</div>';
      results.classList.add('show');
      return;
    }
    results.innerHTML = items.map(function (s) {
      return (
        '<a href="/circles/' + s.circle_id + '/">' +
        '<span class="s-name">' + escapeHtml(s.name) + '</span>' +
        '<span class="s-circle">' + escapeHtml(s.circle_name) + '</span>' +
        '</a>'
      );
    }).join('');
    results.classList.add('show');
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  input.addEventListener('input', function () {
    const query = input.value.trim();
    lastQuery = query;
    clearTimeout(debounceTimer);

    if (!query) {
      results.classList.remove('show');
      results.innerHTML = '';
      return;
    }

    debounceTimer = setTimeout(function () {
      fetch(searchUrl + '?q=' + encodeURIComponent(query))
        .then((res) => res.json())
        .then((data) => {
          if (query !== lastQuery) return; // تجاهل النتائج المتأخرة
          render(data.results || []);
        })
        .catch(() => {
          results.innerHTML = '<div class="no-result">حدث خطأ أثناء البحث</div>';
          results.classList.add('show');
        });
    }, 250);
  });

  document.addEventListener('click', function (e) {
    if (!results.contains(e.target) && e.target !== input) {
      results.classList.remove('show');
    }
  });
});
