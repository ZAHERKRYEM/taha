# نظام إدارة حلقات مسجد طه

مشروع Django لإدارة الحلقات القرآنية: تسجيل الحضور والغياب والإذن، وإضافة الحلقات والطلاب، بحساب إداري واحد فقط.

## المميزات
- تسجيل دخول حصري لحساب إداري واحد (بدون تسجيل عام)
- عرض الحلقات مع نسبة الحضور اليومي
- تسجيل حضور/غياب/إذن لكل طالب (Checkbox ثلاثية الحالة) لأي تاريخ ماضٍ أو حالي
- إحصائية نسبة الحضور لكل حلقة (آخر 30 يوم)
- لوحة تحكم لإضافة حلقة جديدة (مع إمكانية إضافة أستاذ جديد مباشرة) وإضافة طالب
- تصميم متجاوب بالكامل (Mobile-first) — شريط تنقّل سفلي بالموبايل، وشريط علوي بسطح المكتب
- الألوان مستوحاة من شعار المسجد (ذهبي/برونزي دافئ)

## التشغيل محلياً

```bash
# 1) أنشئ بيئة افتراضية (اختياري لكن يُنصح به)
python -m venv venv
source venv/bin/activate      # على ويندوز: venv\Scripts\activate

# 2) ثبّت المتطلبات
pip install -r requirements.txt

# 3) نفّذ الترحيلات (Migrations)
python manage.py makemigrations
python manage.py migrate

# 4) أنشئ الحساب الإداري الوحيد
python manage.py createsuperuser

# 5) شغّل الخادم
python manage.py runserver
```

ثم افتح المتصفح على: `http://127.0.0.1:8000/`

للوصول من جوالك على نفس الشبكة المحلية:
```bash
python manage.py runserver 0.0.0.0:8000
```
ثم من الجوال افتح `http://<عنوان-IP-الخاص-بجهازك>:8000/`

## خط Dubai
الخط المطلوب "Dubai" هو خط من مايكروسوفت وغير متاح عبر Google Fonts. المشروع مهيأ لاستخدامه تلقائياً إن كان مثبتاً على جهاز المستخدم (`local('Dubai')`)، وإلا فسيتم الرجوع لخط بديل قريب شكلاً (Segoe UI / Tahoma).

لتضمين الخط فعلياً داخل الموقع (يظهر بنفس الشكل لكل الزوار بغض النظر عن أجهزتهم):
1. احصل على ملفات الخط بصيغة `.woff2` (Dubai-Regular, Dubai-Medium, Dubai-Bold)
2. ضعها داخل: `halaqat/static/halaqat/fonts/`
3. الأسماء المتوقعة في الكود:
   - `Dubai-Regular.woff2`
   - `Dubai-Medium.woff2`
   - `Dubai-Bold.woff2`

## هيكل المشروع
```
masjid_taha/
├── manage.py
├── requirements.txt
├── masjid_taha/          # إعدادات المشروع
│   ├── settings.py
│   ├── urls.py
├── halaqat/               # التطبيق الرئيسي
│   ├── models.py          # Teacher, Circle, Student, Attendance
│   ├── views.py
│   ├── forms.py
│   ├── urls.py
│   ├── admin.py           # تسجيل النماذج في /django-admin (اختياري للصيانة)
│   ├── templates/halaqat/
│   └── static/halaqat/
│       ├── css/style.css
│       └── fonts/         # ضع ملفات خط Dubai هنا
```

## ملاحظات أمنية قبل النشر الفعلي على الإنترنت
- غيّر `SECRET_KEY` في `settings.py`
- اجعل `DEBUG = False`
- حدد `ALLOWED_HOSTS` بدقة (اسم النطاق فقط)
- استخدم قاعدة بيانات إنتاجية (PostgreSQL مثلاً) بدلاً من SQLite إن كان الاستخدام كبيراً
- فعّل HTTPS
