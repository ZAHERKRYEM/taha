"""
أدوات مساعدة للتواصل مع بوت التلغرام:
- send_telegram_message: إرسال رسالة نصية (تُستخدم لسجلات عمليات لوحة التحكم)
- send_telegram_document: إرسال ملف (تُستخدم للنسخة الاحتياطية اليومية لقاعدة البيانات)

كل الدوال هنا "صامتة الفشل" عمداً: أي خطأ في الاتصال بتلغرام (لا إنترنت،
توكن خاطئ، chat_id غير مُعرَّف...) لن يُسقط الطلب الأساسي في لوحة التحكم؛
فقط يُسجَّل في الـ logger لمراجعته لاحقاً.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger('halaqat.telegram')

TELEGRAM_API_BASE = 'https://api.telegram.org/bot{token}/{method}'
REQUEST_TIMEOUT = 10  # ثوانٍ


def _is_configured():
    return bool(getattr(settings, 'TELEGRAM_BOT_TOKEN', '') and getattr(settings, 'TELEGRAM_CHAT_ID', ''))


def send_telegram_message(text):
    """إرسال رسالة نصية للمحادثة المُعرَّفة في الإعدادات. لا يرفع استثناء عند الفشل."""
    if not _is_configured():
        logger.info('Telegram غير مُهيأ (التوكن أو chat_id فارغ) - تم تجاهل الرسالة: %s', text)
        return False
    try:
        url = TELEGRAM_API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN, method='sendMessage')
        response = requests.post(
            url,
            data={'chat_id': settings.TELEGRAM_CHAT_ID, 'text': text},
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            logger.warning('فشل إرسال رسالة تلغرام: %s - %s', response.status_code, response.text)
            return False
        return True
    except requests.RequestException as exc:
        logger.warning('خطأ اتصال أثناء إرسال رسالة تلغرام: %s', exc)
        return False


def send_telegram_document(file_path, caption=''):
    """إرسال ملف (مثل نسخة قاعدة البيانات) للمحادثة المُعرَّفة في الإعدادات."""
    if not _is_configured():
        logger.info('Telegram غير مُهيأ (التوكن أو chat_id فارغ) - تم تجاهل إرسال الملف: %s', file_path)
        return False
    try:
        url = TELEGRAM_API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN, method='sendDocument')
        with open(file_path, 'rb') as f:
            response = requests.post(
                url,
                data={'chat_id': settings.TELEGRAM_CHAT_ID, 'caption': caption},
                files={'document': f},
                timeout=60,
            )
        if not response.ok:
            logger.warning('فشل إرسال ملف تلغرام: %s - %s', response.status_code, response.text)
            return False
        return True
    except (requests.RequestException, OSError) as exc:
        logger.warning('خطأ أثناء إرسال ملف تلغرام: %s', exc)
        return False
