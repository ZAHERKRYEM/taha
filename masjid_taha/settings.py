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
#  Render يُعيّن DATABASE_URL تلقائياً عند إضافة PostgreSQL service
#  للتطوير المحلي: يرجع تلقائياً إلى SQLite
# ══════════════════════════════════════════════════════════════
DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=600,
    )
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
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL            = 'login'
LOGIN_REDIRECT_URL   = 'circles_list'
LOGOUT_REDIRECT_URL  = 'login'
