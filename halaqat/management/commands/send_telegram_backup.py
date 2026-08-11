"""
أمر إداري لإرسال نسخة احتياطية يومية من قاعدة البيانات إلى بوت التلغرام.

الاستخدام اليدوي:
    python manage.py send_telegram_backup

للجدولة التلقائية اليومية على لينكس، أضف سطراً في crontab (شغّل crontab -e):
    0 23 * * * cd /path/to/masjid_taha && /path/to/venv/bin/python manage.py send_telegram_backup >> /path/to/masjid_taha/telegram_backup.log 2>&1

هذا يرسل الملف الساعة 11 مساءً كل يوم. عدّل التوقيت (0 23) كما يناسبك.
"""
import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from halaqat.telegram_utils import send_telegram_document, send_telegram_message


class Command(BaseCommand):
    help = 'يرسل نسخة احتياطية من قاعدة البيانات (db.sqlite3) إلى بوت التلغرام المُعرَّف في الإعدادات.'

    def handle(self, *args, **options):
        db_path = settings.DATABASES['default'].get('NAME')

        if not db_path or not db_path.exists():
            self.stderr.write(self.style.ERROR(f'ملف قاعدة البيانات غير موجود: {db_path}'))
            return

        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            self.stderr.write(self.style.ERROR(
                'إعدادات تلغرام غير مكتملة. تأكد من تعبئة TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID '
                'في ملف masjid_taha/telegram_secrets.py'
            ))
            return

        today_str = datetime.date.today().isoformat()
        caption = f'📦 نسخة احتياطية يومية - قاعدة بيانات مسجد طه - {today_str}'

        self.stdout.write('جارٍ إرسال النسخة الاحتياطية إلى تلغرام...')
        ok = send_telegram_document(db_path, caption=caption)

        if ok:
            self.stdout.write(self.style.SUCCESS('تم إرسال النسخة الاحتياطية بنجاح ✓'))
        else:
            self.stderr.write(self.style.ERROR(
                'فشل إرسال النسخة الاحتياطية. راجع الـ logs، وتأكد من صحة التوكن و chat_id، ومن وجود اتصال إنترنت.'
            ))
            send_telegram_message(f'⚠️ فشل إرسال النسخة الاحتياطية اليومية بتاريخ {today_str}')
