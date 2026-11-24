"""
اختبارات الحماية (شغّلها بـ: python manage.py test halaqat):
  • كل صفحة/نقطة نهاية في التطبيق تحوّل الزائر غير المسجَّل إلى شاشة الدخول (لا استثناء إلا شاشة الدخول نفسها).
  • شاشة الدخول لا تعرض أي تبويبات أو قوائم تنقّل.
  • من لديه جلسة سارية يُحوَّل من شاشة الدخول إلى الرئيسية بدل رؤية النموذج مع التبويبات.
  • صفحات النظام لا تُخزَّن في المتصفح، وبعد الخروج تتطلب الصفحات الدخول من جديد.
"""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from halaqat import cache_utils
from halaqat import urls as halaqat_urls


def _app_paths():
    """كل مسارات halaqat/urls.py المسمّاة مع تعويض المعاملات بقيم تجريبية."""
    out = []
    for p in halaqat_urls.urlpatterns:
        name = getattr(p, 'name', None)
        if not name:
            continue
        route = str(p.pattern)
        route = re.sub(r'<str:[^>]+>', 'xlsx', route)
        route = re.sub(r'<(?:int|slug|path|uuid):[^>]+>', '1', route)
        out.append((name, '/' + route))
    return out


class SecurityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # لا نريد خيط التحميل المسبق للكاش أثناء الاختبارات
        cls._orig_warm = cache_utils.warm_cache_async
        cache_utils.warm_cache_async = lambda *a, **k: False

    @classmethod
    def tearDownClass(cls):
        cache_utils.warm_cache_async = cls._orig_warm
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user('supervisor', password='Str0ng-pass-12345')

    def test_every_page_redirects_anonymous_visitors_to_login(self):
        paths = _app_paths()
        self.assertGreater(len(paths), 40)                     # نتأكد أننا نفحص المسارات فعلاً
        for name, path in paths:
            if name == 'login':
                continue
            for method in ('get', 'post'):
                resp = getattr(self.client, method)(path)
                self.assertIn(resp.status_code, (302, 405), f'{method.upper()} {path} ({name}) → {resp.status_code}')
                if resp.status_code == 302 and name != 'logout':
                    self.assertIn('next=', resp['Location'], f'{method.upper()} {path} لم يُحوَّل لشاشة الدخول')

    def test_login_screen_shows_no_navigation_tabs(self):
        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 200)
        for marker in ('bottom-nav', 'top-nav', 'side-drawer', 'brand-bar'):
            self.assertNotContains(resp, marker)

    def test_authenticated_user_is_redirected_away_from_login_screen(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('login'))
        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)

    def test_pages_are_not_cacheable_by_the_browser(self):
        self.assertIn('no-store', self.client.get(reverse('login'))['Cache-Control'])
        self.client.force_login(self.user)
        self.assertIn('no-store', self.client.get(reverse('help_page'))['Cache-Control'])

    def test_after_logout_pages_require_login_again(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('help_page')).status_code, 200)
        self.client.post(reverse('logout'))
        resp = self.client.get(reverse('help_page'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('next=', resp['Location'])
