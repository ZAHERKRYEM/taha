import logging
import requests
from django.conf import settings

logger = logging.getLogger('halaqat.whatsapp')
REQUEST_TIMEOUT = 30


def _is_configured():
    return bool(getattr(settings, 'WAHA_RENDER_URL', '') and getattr(settings, 'WAHA_API_KEY', ''))


def normalize_chat_id(phone):
    """Normalize a phone number to a WAHA WhatsApp chatId format.

    Expected input examples: +963942123456, 0942123456, 942123456
    Output: 963942123456@c.us
    """
    if not phone:
        return ''
    digits = ''.join(ch for ch in phone if ch.isdigit())
    if digits.startswith('0'):
        digits = digits[1:]
    if digits.startswith('963'):
        digits = digits
    elif digits.startswith('9'):
        digits = f'963{digits}'
    else:
        return ''
    return f'{digits}@c.us'


def send_whatsapp_text(chat_id, text):
    if not _is_configured():
        logger.warning('WhatsApp not configured - ignored message for %s', chat_id)
        return False

    url = f"{settings.WAHA_RENDER_URL}/api/sendText"
    headers = {
        "X-Api-Key": settings.WAHA_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "session": "taha",
        "chatId": chat_id,
        "text": text,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        if not response.ok:
            logger.warning('WhatsApp send failed %s: %s', response.status_code, response.text)
            return False
        return True
    except requests.RequestException as exc:
        logger.warning('WhatsApp send request error: %s', exc)
        return False
