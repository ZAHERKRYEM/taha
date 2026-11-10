// بحث فوري عن طالب بالاسم (محلياً في المتصفح) - الضغط على الاسم ينقل لصفحة حضوره، وعلى الحلقة لصفحة الحلقة
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
        '<div class="search-result-row">' +
        '<a href="/students/' + s.id + '/profile/" title="صفحة حضور الطالب">' +
        '<span class="s-name">' + escapeHtml(s.name) + '</span>' +
        '</a>' +
        '<a class="s-circle" style="margin:0 10px" href="/circles/' + s.circle_id + '/" title="فتح صفحة الحلقة">' + escapeHtml(s.circle_name) + '</a>' +
        '</div>'
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
      // البحث محلياً في المتصفح (StudentIndex) مع رجوع للسيرفر إن لم يتوفر الفهرس
      const run = window.StudentIndex
        ? window.StudentIndex.search(query, 15)
        : fetch(searchUrl + '?q=' + encodeURIComponent(query)).then((res) => res.json()).then((d) => d.results || []);
      run
        .then((items) => {
          if (query !== lastQuery) return; // تجاهل النتائج المتأخرة
          render(items);
        })
        .catch(() => {
          results.innerHTML = '<div class="no-result">حدث خطأ أثناء البحث</div>';
          results.classList.add('show');
        });
    }, 80);
  });

  document.addEventListener('click', function (e) {
    if (!results.contains(e.target) && e.target !== input) {
      results.classList.remove('show');
    }
  });
});
