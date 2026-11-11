"""
أنواع الحسابات:
  - الحساب الإداري (superuser/staff أو أي مستخدم ليس ضمن مجموعة المشاهدين): صلاحيات كاملة.
  - حساب «مشاهد»: يرى صفحة الإحصائيات وصفحة السبر فقط (قراءة فقط، بلا تسجيل/تعديل/حذف).
"""
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import resolve, Resolver404

VIEWER_GROUP = 'مشاهد'

# أسماء المسارات المسموح بها لحساب المشاهد
VIEWER_ALLOWED_URLS = {
    'login', 'logout',
    'stats_page', 'export_stats_pdf',
    'sabr_page', 'sabr_student_info', 'sabr_add', 'sabr_update',   # المشاهد يضيف ويعدّل السبر (بدون حذف)
    'help_page',
    'students_index',                    # قائمة الأسماء للبحث المحلي
    'student_profile', 'student_quick_stats',   # الضغط على اسم الطالب من الإحصائيات/السبر
}


def is_viewer(user):
    if not user.is_authenticated or user.is_superuser:
        return False
    cache = getattr(user, '_is_viewer_cache', None)
    if cache is None:
        cache = user.groups.filter(name=VIEWER_GROUP).exists()
        user._is_viewer_cache = cache
    return cache


class ViewerAccessMiddleware:
    """يحصر حساب المشاهد في الصفحات المسموح بها فقط."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and is_viewer(user):
            try:
                name = resolve(request.path_info).url_name
            except Resolver404:
                name = None
            if name not in VIEWER_ALLOWED_URLS:
                is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                if is_ajax or request.method != 'GET':
                    return JsonResponse({'ok': False, 'error': 'هذا الحساب للعرض فقط'}, status=403)
                return redirect('stats_page')
        return self.get_response(request)


# عناصر التنقّل: (اسم المسار، المفتاح active_nav، الأيقونة، النص)
_NAV_MAIN = [
    ('home', 'home', '🏠', 'الرئيسية'),
    ('circles_list', 'circles', '📖', 'الحلقات'),
    ('courses_list', 'courses', '🎓', 'الدورات'),
    ('absentees_list', 'absentees', '🚫', 'الغائبون'),
    ('sabr_page', 'sabr', '📝', 'السبر'),
]
_NAV_MORE = [
    ('teachers_list', 'teachers', '👨‍🏫', 'الأساتذة'),
    ('stats_page', 'stats', '📊', 'الإحصائيات'),
    ('admin_panel', 'admin', '⚙️', 'لوحة التحكم'),
    ('developer_page', 'developer', '🛠', 'المطور'),
    ('help_page', 'help', '❓', 'كيفية الاستخدام'),
]
_NAV_VIEWER_MAIN = [
    ('stats_page', 'stats', '📊', 'الإحصائيات'),
    ('sabr_page', 'sabr', '📝', 'السبر'),
]
_NAV_VIEWER_MORE = [
    ('help_page', 'help', '❓', 'كيفية الاستخدام'),
]


def _nav(items):
    from django.urls import reverse
    return [{'url': reverse(n), 'key': k, 'icon': i, 'label': l} for n, k, i, l in items]


def roles_context(request):
    user = getattr(request, 'user', None)
    viewer = bool(user and is_viewer(user))
    if not (user and user.is_authenticated):
        return {'is_viewer': False}
    return {
        'is_viewer': viewer,
        'nav_main': _nav(_NAV_VIEWER_MAIN if viewer else _NAV_MAIN),
        'nav_more': _nav(_NAV_VIEWER_MORE if viewer else _NAV_MORE),
    }
