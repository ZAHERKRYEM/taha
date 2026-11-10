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
    'sabr_page', 'sabr_student_info',
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


def roles_context(request):
    user = getattr(request, 'user', None)
    return {'is_viewer': bool(user and is_viewer(user))}
