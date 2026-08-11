"""
إعدادات مشروع نظام إدارة حلقات مسجد طه
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ⚠️ غيّر هذا المفتاح قبل النشر الفعلي على الإنترنت
SECRET_KEY = 'django-insecure-CHANGE-THIS-KEY-BEFORE-PRODUCTION-1234567890'

# ⚠️ اجعلها False عند النشر الفعلي، وحدد ALLOWED_HOSTS
DEBUG = True

ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = [
    "https://taha-9f3c.onrender.com",
]
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

# قاعدة البيانات - SQLite للتطوير المحلي
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# اللغة والتوطين - عربي / يمين لليسار
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Asia/Riyadh'  # عدّلها حسب منطقتك الزمنية
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---- إعدادات تسجيل الدخول ----
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'circles_list'
LOGOUT_REDIRECT_URL = 'login'

# ---- إعدادات بوت تلغرام (نسخ احتياطي يومي + سجل عمليات لوحة التحكم) ----
# القيم الفعلية (التوكن الحقيقي) موجودة في ملف telegram_secrets.py المحلي
# وهو مستثنى من git عمداً حماية للسر. إن لم يكن موجوداً، تُقرأ القيم من
# متغيرات البيئة كخطة بديلة.
try:
    from .telegram_secrets import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# فعّل/عطّل إرسال سجل عمليات لوحة التحكم (حذف/تعديل) لتلغرام
TELEGRAM_LOG_ADMIN_ACTIONS = True

# ---- إعدادات واتساب WAHA ----
# القيم الفعلية موجودة في ملف whatsapp_secrets.py المحلي أو متغيرات البيئة.

WAHA_RENDER_URL ="https://taha-wa.onrender.com"
WAHA_API_KEY ="12345678"
