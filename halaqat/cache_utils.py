"""
كاش في ذاكرة التطبيق (LocMemCache) لتسريع الصفحات رغم بُعد قاعدة البيانات (Supabase).

الفكرة:
  • عند تشغيل التطبيق (wsgi/asgi) يبدأ خيط خلفي يملأ الذاكرة مسبقاً بكل ما تحتاجه
    الصفحات باستمرار: قائمة الحلقات وأعداد طلابها، فهرس الطلاب، الأساتذة غير المرتبطين،
    وحساب الإحصائيات الافتراضي (الأثقل). فيجد أول زائر البيانات جاهزة بدل انتظار عشرات
    الاستعلامات عبر الشبكة.
  • أي إضافة/تعديل/حذف يُبطل الكاش المتأثر فوراً (signals.py)، فلا تظهر بيانات قديمة.
  • الكاش لكل عملية (process): يُنصح بتشغيل gunicorn بعملية واحدة وعدة خيوط
    (--workers 1 --threads 4). مع عدة عمليات تبقى الصلاحية محدودة بـ TTL (15 دقيقة).
  • كاش قاعدة البيانات (default / DatabaseCache) يبقى كما هو ولا يتأثر.

المجموعتان:
  reference — بيانات تتغيّر نادراً: الحلقات، الطلاب، الأساتذة.
  stats     — نواتج الحساب الثقيل للإحصائيات؛ تُبطَل مع أي تعديل على سجلات الحضور/السبر
              (برقم نسخة داخل المفتاح، فلا تتراكم نسخ قديمة في الذاكرة).
"""
import hashlib
import json
import logging
import os
import threading
import time

from django.core.cache import caches

logger = logging.getLogger('halaqat.cache')

REF_TTL = 15 * 60
STATS_TTL = 15 * 60

_KEY_CIRCLES = 'ref:circles'
_KEY_STUDENTS = 'ref:students_index'
_KEY_FREE_TEACHERS = 'ref:free_teachers'
_REF_KEYS = (_KEY_CIRCLES, _KEY_STUDENTS, _KEY_FREE_TEACHERS)

_MISSING = object()
_lock = threading.Lock()
_stats_version = 1
_stats_keys = set()          # مفاتيح النسخة الحالية، لحذفها فور الإبطال
_warm_pid = None             # رقم العملية التي بدأ فيها التحميل المسبق
_last_warm = {}              # آخر نتيجة تحميل مسبق (للعرض في صفحة المطور)


def _mem():
    """ذاكرة العملية؛ وإن لم يُعرَّف التخزين 'memory' في الإعدادات نرجع للكاش الافتراضي."""
    try:
        return caches['memory']
    except Exception:
        return caches['default']


# ══════════════════════════════════════════════════════════════
#  البيانات المرجعية
# ══════════════════════════════════════════════════════════════

def _ref(key, builder, ttl=REF_TTL):
    mem = _mem()
    val = mem.get(key, _MISSING)
    if val is _MISSING:
        val = builder()
        mem.set(key, val, ttl)
    return val


def _build_circles():
    from django.db.models import Count
    from .models import Circle
    qs = (Circle.objects.select_related('teacher').annotate(n=Count('students'))
          .order_by('display_order', 'name', 'id'))
    return [{
        'id': c.id, 'name': c.name, 'description': c.description, 'display_order': c.display_order,
        'teacher': {'id': c.teacher_id, 'name': c.teacher.name} if c.teacher_id else None,
        'students': c.n,
    } for c in qs]


def circles():
    """كل الحلقات مرتبةً (id, name, description, display_order, teacher{id,name}|None, students)."""
    return _ref(_KEY_CIRCLES, _build_circles)


def _build_students_index():
    from .models import Student
    rows = list(Student.objects.select_related('circle').order_by('name')
                .values_list('id', 'name', 'circle_id', 'circle__name'))
    payload = json.dumps(rows, ensure_ascii=False, separators=(',', ':'))
    return {'v': hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16], 'payload': payload, 'rows': rows}


def students_index():
    """{'v': نسخة, 'payload': JSON جاهز, 'rows': [(id, اسم, id الحلقة, اسم الحلقة)]}."""
    return _ref(_KEY_STUDENTS, _build_students_index)


def _build_free_teachers():
    from .models import Teacher
    qs = (Teacher.objects.filter(circles__isnull=True, courses__isnull=True)
          .distinct().order_by('name'))
    return [{'id': t.id, 'name': t.name, 'phone': t.phone} for t in qs]


def free_teachers():
    """الأساتذة غير المرتبطين بأي حلقة أو دورة (يُسجَّل لهم «تفقد عام»)."""
    return _ref(_KEY_FREE_TEACHERS, _build_free_teachers)


def invalidate_reference():
    _mem().delete_many(list(_REF_KEYS))


# ══════════════════════════════════════════════════════════════
#  الإحصائيات
# ══════════════════════════════════════════════════════════════

def stats_cached(name, builder, ttl=STATS_TTL):
    """يعيد ناتج builder() من الذاكرة إن وُجد لنفس (name) في النسخة الحالية، وإلا يحسبه ويخزّنه."""
    global _stats_version
    with _lock:
        version = _stats_version
    key = f'stats:{version}:{name}'
    mem = _mem()
    val = mem.get(key, _MISSING)
    if val is _MISSING:
        val = builder()
        with _lock:
            if version == _stats_version:       # لم يُبطَل أثناء الحساب → نخزّن
                mem.set(key, val, ttl)
                _stats_keys.add(key)
    return val


def invalidate_stats():
    global _stats_version
    with _lock:
        _stats_version += 1
        stale = list(_stats_keys)
        _stats_keys.clear()
    if stale:
        _mem().delete_many(stale)


def invalidate_all():
    """يُستدعى بعد العمليات التي لا ترسل signals (bulk_create، الاستيراد، الترحيل…)."""
    invalidate_reference()
    invalidate_stats()


# ══════════════════════════════════════════════════════════════
#  التحميل المسبق عند تشغيل التطبيق
# ══════════════════════════════════════════════════════════════

def warm_cache(close_connections=True):
    """يملأ الذاكرة بكل ما سبق (ويعيد حساب ما أُبطل). آمن للاستدعاء أكثر من مرة."""
    from django.db import connections
    from django.utils import timezone
    t0 = time.monotonic()
    ok, failed = [], []

    def step(label, fn):
        try:
            fn()
            ok.append(label)
        except Exception:
            failed.append(label)
            logger.exception('تعذّر تحميل «%s» في الكاش', label)

    step('الحلقات وأعداد الطلاب', circles)
    step('فهرس الطلاب', students_index)
    step('الأساتذة غير المرتبطين', free_teachers)

    def _stats():
        from django.http import HttpRequest
        from . import views
        req = HttpRequest()                      # GET فارغ = الفلاتر الافتراضية
        req.method = 'GET'
        views._stats_context(req, paginate=True)
    step('الإحصائيات الافتراضية', _stats)

    _last_warm.update({
        'at': timezone.localtime().strftime('%Y-%m-%d %H:%M:%S'), 'seconds': round(time.monotonic() - t0, 2),
        'ok': ok, 'failed': failed,
    })
    logger.info('تم تحميل الكاش مسبقاً في %.2f ثانية: %s', time.monotonic() - t0, '، '.join(ok))
    if close_connections:
        connections.close_all()      # أغلق اتصال الخيط الخلفي بقاعدة البيانات
    return _last_warm


def warm_cache_async(delay=1.5):
    """يبدأ التحميل المسبق في خيط خلفي (مرة واحدة لكل عملية) دون تعطيل إقلاع الخادم."""
    global _warm_pid
    with _lock:
        if _warm_pid == os.getpid():
            return False
        _warm_pid = os.getpid()

    def _run():
        time.sleep(delay)
        try:
            warm_cache()
        except Exception:
            logger.exception('فشل التحميل المسبق للكاش')

    threading.Thread(target=_run, name='taha-cache-warm', daemon=True).start()
    return True


def rate_limit(key, limit, window=3600):
    """عدّاد بسيط في ذاكرة العملية: يعيد True إن كان الطلب مسموحاً (ويزيد العدّاد)، False إن بلغ الحد خلال النافذة."""
    mem = _mem()
    now = time.time()
    with _lock:
        entry = mem.get(key, None)
        if entry is None or entry[1] <= now:
            mem.set(key, (1, now + window), window)
            return True
        count, reset = entry
        if count >= limit:
            return False
        mem.set(key, (count + 1, reset), max(1, int(reset - now)))
        return True


def status():
    """حالة الكاش لعرضها في صفحة المطور."""
    mem = _mem()
    return {
        'last_warm': dict(_last_warm),
        'stats_version': _stats_version,
        'cached': {
            'الحلقات': mem.get(_KEY_CIRCLES, _MISSING) is not _MISSING,
            'فهرس الطلاب': mem.get(_KEY_STUDENTS, _MISSING) is not _MISSING,
            'الأساتذة غير المرتبطين': mem.get(_KEY_FREE_TEACHERS, _MISSING) is not _MISSING,
            'الإحصائيات': bool(_stats_keys),
        },
    }


class WarmupMiddleware:
    """احتياط: إن لم يُشغَّل التحميل المسبق في هذه العملية (مثل gunicorn --preload) يبدأ مع أول طلب."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _warm_pid != os.getpid():
            warm_cache_async(delay=0)
        return self.get_response(request)
