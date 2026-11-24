"""
إعدادات مشروع نظام إدارة حلقات مسجد طه
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
جميع البيانات الحساسة (كلمات المرور، التوكنات، المفاتيح) تُقرأ حصراً
من متغيرات البيئة — لا يوجد أي سر مكتوب بشكل مباشر في هذا الملف.

على Render:  Dashboard → Service → Environment → Add Environment Variable
للتطوير المحلي: انسخ .env.example إلى .env واملأ القيم
"""
import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# ══════════════════════════════════════════════════════════════
#  الإعدادات الأساسية  (كلها من متغيرات البيئة)
# ══════════════════════════════════════════════════════════════

DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

# مطلوب دائماً — إن غاب في الإنتاج يرفع استثناء واضحاً
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-local-dev-only-change-before-production' if DEBUG else ''
)
if not SECRET_KEY:
    raise RuntimeError(
        '⚠️ متغير البيئة SECRET_KEY غير مُعيَّن! '
        'أضفه في لوحة Render أو في ملف .env المحلي.'
    )

# المضيفون المسموح بهم — فصل بفواصل: "taha.onrender.com,www.taha.com"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]

# أصول CSRF الموثوقة — مطلوبة لـ HTTPS على Render
# مثال: "https://taha-9f3c.onrender.com,https://www.yoursite.com"
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
    if o.strip()
]

# ══════════════════════════════════════════════════════════════
#  قاعدة البيانات
#  الإنتاج (Render + Supabase): متغيّرا البيئة DATABASE_URL و DB_PASSWORD
#    DATABASE_URL = postgresql://postgres.<ref>@aws-0-<region>.pooler.supabase.com:5432/postgres
#    DB_PASSWORD  = كلمة مرور قاعدة البيانات (منفصلة، فلا حاجة لترميز الرموز الخاصة)
#  (يُقبل أيضاً رابط كامل يحوي كلمة المرور بدل DB_PASSWORD)
#  التطوير المحلي: بدون DATABASE_URL يرجع تلقائياً إلى SQLite
# ══════════════════════════════════════════════════════════════
def _clean_database_url(url):
    """يزيل علامات التنصيص والمعاملات التي لا يفهمها libpq/psycopg (مثل ?pgbouncer=true)."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    url = (url or '').strip().strip('"').strip("'").strip()
    if not url:
        return ''
    import re
    url = re.sub(r':\[[^\]@]*\]@', '@', url)     # نائب «[YOUR-PASSWORD]» المنسوخ من Supabase
    parts = urlsplit(url)
    drop = {'pgbouncer', 'connection_limit', 'pool_timeout', 'schema'}
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in drop])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))


_DATABASE_URL = _clean_database_url(os.environ.get('DATABASE_URL', ''))

if _DATABASE_URL:
    _db = dj_database_url.parse(
        _DATABASE_URL,
        conn_max_age=int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        conn_health_checks=True,       # يتحقق من الاتصال بعد استيقاظ الخادم من السكون
        ssl_require=True,              # Supabase يتطلب SSL
    )
    _db_password = os.environ.get('DB_PASSWORD', '').strip()
    if _db_password:
        _db['PASSWORD'] = _db_password
    if str(_db.get('PORT')) == '6543':
        # Transaction Pooler: لا يدعم المؤشرات من جهة الخادم ولا الاتصالات الدائمة
        _db['DISABLE_SERVER_SIDE_CURSORS'] = True
        _db['CONN_MAX_AGE'] = 0
    DATABASES = {'default': _db}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ══════════════════════════════════════════════════════════════
#  التخزين المؤقت داخل قاعدة البيانات (لا يضيع عند سكون الخادم)
#  يُنشأ الجدول مرة واحدة بالأمر:  python manage.py createcachetable
# ══════════════════════════════════════════════════════════════
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache',
        'TIMEOUT': 60 * 60 * 24,
        'OPTIONS': {'MAX_ENTRIES': 5000},
    },
    # كاش في ذاكرة التطبيق نفسه (بلا أي استعلام): يُملأ مسبقاً عند التشغيل وتُبطله signals عند التعديل.
    # انظر halaqat/cache_utils.py — يُنصح بتشغيل gunicorn بعملية واحدة: --workers 1 --threads 4
    'memory': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'taha-memory',
        'TIMEOUT': 60 * 15,
        'OPTIONS': {'MAX_ENTRIES': 300},
    },
}

# ══════════════════════════════════════════════════════════════
#  تلغرام  (نسخ احتياطي + سجل عمليات لوحة التحكم)
# ══════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')

# فعّل/عطّل إرسال سجل حذف/تعديل لوحة التحكم إلى تلغرام
TELEGRAM_LOG_ADMIN_ACTIONS = True

# ══════════════════════════════════════════════════════════════
#  واتساب WAHA
# ══════════════════════════════════════════════════════════════
WAHA_RENDER_URL = os.environ.get('WAHA_RENDER_URL', '')
WAHA_API_KEY    = os.environ.get('WAHA_API_KEY', '')

# ══════════════════════════════════════════════════════════════
#  إعدادات Django الثابتة
# ══════════════════════════════════════════════════════════════
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'halaqat',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # تقديم الملفات الثابتة في الإنتاج
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'halaqat.roles.ViewerAccessMiddleware',   # حساب «مشاهد»: الإحصائيات والسبر فقط
    'halaqat.cache_utils.WarmupMiddleware',   # احتياط للتحميل المسبق للكاش (انظر cache_utils)
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'halaqat.security.NoStoreMiddleware',     # لا تخزين لصفحات النظام في المتصفح (زر الرجوع بعد الخروج)
]

ROOT_URLCONF = 'masjid_taha.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'halaqat.roles.roles_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'masjid_taha.wsgi.application'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ar'
TIME_ZONE     = 'Asia/Riyadh'
USE_I18N = True
USE_TZ   = True

STATIC_URL  = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL            = 'login'
LOGIN_REDIRECT_URL   = 'home'
LOGOUT_REDIRECT_URL  = 'login'

# ── المساعد الإحصائي بالذكاء الاصطناعي (اختياري) ──────────────────────────
# بدون المفتاح تعمل الصفحة بوضع «تعديل التفسير» اليدوي فقط. النموذج يستقبل السؤال وأسماء الحلقات فقط (لا بيانات طلاب).
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-haiku-5-5')
ASSISTANT_RATE_LIMIT_PER_HOUR = int(os.environ.get('ASSISTANT_RATE_LIMIT_PER_HOUR', '30'))

# ── أمان الجلسة وملفات الكوكيز ────────────────────────────────────────────
# مدة بقاء تسجيل الدخول (الافتراضي أسبوعان). قلّلها على الأجهزة المشتركة: SESSION_AGE_HOURS=12
# أو اجعل الجلسة تنتهي بإغلاق المتصفح: SESSION_EXPIRE_AT_BROWSER_CLOSE=true
SESSION_COOKIE_AGE = int(os.environ.get('SESSION_AGE_HOURS', str(14 * 24))) * 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = os.environ.get('SESSION_EXPIRE_AT_BROWSER_CLOSE', 'False').lower() == 'true'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
# في الإنتاج (HTTPS على Render) لا تُرسَل الكوكيز إلا مشفّرة. للتجربة عبر http محلياً: SESSION_COOKIE_SECURE=false
_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', str(not DEBUG)).lower() == 'true'
SESSION_COOKIE_SECURE = _COOKIE_SECURE
CSRF_COOKIE_SECURE = _COOKIE_SECURE
if _COOKIE_SECURE:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')   # Render ينهي TLS عند الوسيط
