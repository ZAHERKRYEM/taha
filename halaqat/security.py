"""
حماية إضافية للصفحات:
  NoStoreMiddleware — يمنع المتصفح والوسطاء من تخزين صفحات النظام، فلا يعيد زر «رجوع» عرض صفحة
  سبق فتحها بعد تسجيل الخروج أو انتهاء الجلسة (يُرسل Cache-Control: no-store).
الملفات الثابتة تخدمها WhiteNoise قبل هذه الطبقة فلا تتأثر ويبقى تخزينها مفعّلاً.
"""
from django.utils.cache import add_never_cache_headers


class NoStoreMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        add_never_cache_headers(response)
        return response
