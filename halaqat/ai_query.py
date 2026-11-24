"""
المساعد الإحصائي: سؤال بالعربية ⇒ «مواصفة» منظّمة ⇒ جدول (مع تصدير Excel وPDF).

مبدأ الأمان: النموذج لا يكتب SQL ولا يرى بيانات الطلاب.
  1) يستقبل السؤال + تاريخ اليوم + أسماء الحلقات فقط، ويُرجع مواصفة JSON عبر أداة build_query.
  2) validate_spec تنظّف المواصفة بقوائم مسموحة (مقاييس، تجميعات، عوامل مقارنة، حدود).
  3) run_spec تنفّذها بمحرّك الإحصائيات نفسه (views._stats_context) فتتطابق الأرقام مع صفحة الإحصائيات
     وتستفيد من نفس الكاش، ثم تجمّع/تفرز/تحدّ النتائج في بايثون. لا يُنفَّذ أي نص من النموذج.

بنية المواصفة (spec):
  subject        students | teachers
  group_by       person (صف لكل فرد) | circle (صف لكل حلقة) | month (صف لكل شهر)
  metrics        rate present late absent excused unrecorded sessions sabr recitations ayahs people
  date_from/to   YYYY-MM-DD أو None (= كل الفترة)
  circles        معرّفات الحلقات (الحلقة الحالية للطالب)
  name_contains  جزء من الاسم
  age_min/max    فلتر العمر
  monthly_columns  عمود نسبة لكل شهر (مع group_by=person)
  conditions     [{metric, op, value}] مثل الغياب ≥ 3
  sort_by/sort_dir/limit/title
"""
import datetime
import json
import logging
import math
import re

logger = logging.getLogger('halaqat.assistant')

# ───────────────────────── التعريفات المسموحة ─────────────────────────

BOTH = ('students', 'teachers')
STUDENTS = ('students',)

# المفتاح: (الاسم العربي، النوع، الفئات المسموحة)
METRICS = {
    'rate':        ('نسبة الحضور', 'pct', BOTH),
    'present':     ('حاضر', 'int', BOTH),
    'late':        ('متأخر', 'int', BOTH),
    'absent':      ('غائب', 'int', BOTH),
    'excused':     ('بإذن', 'int', BOTH),
    'unrecorded':  ('غير مسجَّل', 'int', BOTH),
    'sessions':    ('أيام الدوام', 'int', BOTH),
    'sabr':        ('مرات السبر', 'int', STUDENTS),
    'recitations': ('مرات التسميع', 'int', STUDENTS),
    'ayahs':       ('الآيات المُسمَّعة', 'int', STUDENTS),
    'people':      ('العدد', 'int', BOTH),                  # عند التجميع بالحلقة أو الشهر فقط
}
DEFAULT_METRICS = ['rate', 'present', 'late', 'absent', 'excused']
SUM_KEYS = ('present', 'late', 'absent', 'excused', 'unrecorded', 'sessions', 'sabr', 'recitations', 'ayahs')
GROUPS = {'person': 'لكل فرد', 'circle': 'لكل حلقة', 'month': 'لكل شهر'}
OPS = {'>': 'أكبر من', '>=': 'لا يقل عن', '<': 'أصغر من', '<=': 'لا يزيد عن', '==': 'يساوي'}
MAX_LIMIT = 500
DEFAULT_LIMIT = 50
MAX_CONDITIONS = 5

EXAMPLES = [
    'من هم الطلاب الأكثر غياباً هذا الشهر؟',
    'رتّب الحلقات حسب نسبة الحضور في آخر 3 أشهر',
    'من غاب أكثر من 3 مرات في الشهر الماضي؟',
    'كم آية سمّع كل طالب هذا الشهر؟',
    'نسبة حضور الأساتذة شهرياً',
]


class AssistantError(Exception):
    """خطأ برسالة عربية جاهزة للعرض للمستخدم."""

    def __init__(self, message, code='error'):
        super().__init__(message)
        self.message = message
        self.code = code


def norm_ar(s):
    s = re.sub('[\u064B-\u0652\u0670\u0640]', '', str(s or ''))
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ى', 'ي'), ('ة', 'ه'), ('ؤ', 'و'), ('ئ', 'ي')):
        s = s.replace(a, b)
    return ' '.join(s.split()).lower()


def allowed_metrics(subject, group_by):
    out = [k for k, (_, _, subs) in METRICS.items() if subject in subs]
    if group_by == 'person' and 'people' in out:
        out.remove('people')                       # «العدد» لا معنى له لصف فرد واحد
    return out


def metric_label(key, subject='students'):
    if key == 'people':
        return 'عدد الطلاب' if subject == 'students' else 'عدد الأساتذة'
    return METRICS[key][0]


# ───────────────────────── التحقق من المواصفة ─────────────────────────

def resolve_circles(items, circles):
    """يحوّل أسماء/معرّفات حلقات إلى معرّفات حقيقية. يعيد (ids، تحذيرات)."""
    by_id = {c['id']: c for c in circles}
    by_norm = {}
    for c in circles:
        by_norm.setdefault(norm_ar(c['name']), []).append(c['id'])
    ids, warns = [], []
    for it in items if isinstance(items, (list, tuple)) else []:
        found = []
        if isinstance(it, int) and not isinstance(it, bool):
            found = [it] if it in by_id else []
        elif isinstance(it, str):
            s = it.strip()
            if s.isdigit() and int(s) in by_id:
                found = [int(s)]
            else:
                n = norm_ar(s)
                if n in by_norm:
                    found = list(by_norm[n])
                elif len(n) >= 3:                  # مطابقة جزئية (مثلاً «أبي» أو «حلقة أبي»)
                    found = [i for nm, lst in by_norm.items() if n in nm or nm in n for i in lst]
        if not found:
            warns.append(f'لم أجد حلقة باسم «{str(it)[:40]}» فتم تجاهلها')
        for i in found:
            if i not in ids:
                ids.append(i)
    return ids, warns


def _iso(v):
    if not v:
        return None
    try:
        return datetime.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def _int_or_none(v, lo, hi):
    try:
        if v is None or str(v).strip() == '':
            return None
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def validate_spec(raw, circles, today):
    """ينظّف مواصفة خام (من النموذج أو من نموذج التعديل). يعيد (spec، تحذيرات)."""
    warns = []
    raw = raw if isinstance(raw, dict) else {}

    def _s(key):                                   # قيمة نصيّة فقط (يمنع TypeError عند وصول قوائم/قواميس)
        v = raw.get(key)
        return v if isinstance(v, str) else None

    subject = _s('subject') if _s('subject') in BOTH else 'students'
    group_by = _s('group_by') if _s('group_by') in GROUPS else 'person'
    if subject == 'teachers' and group_by == 'circle':
        group_by = 'person'
        warns.append('تجميع الأساتذة بالحلقة غير متاح؛ عُرض لكل أستاذ')

    allowed = allowed_metrics(subject, group_by)
    metrics = []
    for m in raw.get('metrics') if isinstance(raw.get('metrics'), (list, tuple)) else []:
        if not isinstance(m, str):
            continue
        if m in allowed and m not in metrics:
            metrics.append(m)
        elif m in METRICS and m not in allowed:
            warns.append(f'المقياس «{metric_label(m, subject)}» غير متاح مع هذا التجميع فتم تجاهله')
    if not metrics:
        metrics = [m for m in DEFAULT_METRICS if m in allowed]
    if group_by != 'person' and 'people' in allowed and 'people' not in metrics:
        metrics.insert(0, 'people')

    d_from, d_to = _iso(raw.get('date_from')), _iso(raw.get('date_to'))
    if d_to and d_to > today:
        d_to = today
    if d_from and d_from > today:
        d_from = today
    if d_from and d_to and d_from > d_to:
        d_from, d_to = d_to, d_from

    circle_ids = []
    if subject == 'students':
        circle_ids, w = resolve_circles(raw.get('circles') or [], circles)
        warns += w
    elif raw.get('circles'):
        warns.append('فلتر الحلقة غير مدعوم للأساتذة فتم تجاهله')

    age_min = age_max = None
    if subject == 'students':
        age_min, age_max = _int_or_none(raw.get('age_min'), 0, 100), _int_or_none(raw.get('age_max'), 0, 100)
        if age_min is not None and age_max is not None and age_min > age_max:
            age_min, age_max = age_max, age_min

    conditions = []
    for c in raw.get('conditions') if isinstance(raw.get('conditions'), (list, tuple)) else []:
        if len(conditions) >= MAX_CONDITIONS:
            warns.append('تم الاكتفاء بأول 5 شروط')
            break
        if not isinstance(c, dict):
            continue
        metric, op = c.get('metric'), c.get('op')
        if not isinstance(metric, str) or not isinstance(op, str):
            continue
        try:
            value = float(c.get('value'))
        except (TypeError, ValueError):
            continue
        if metric not in allowed or op not in OPS or not math.isfinite(value) or abs(value) > 1e9:
            warns.append('تم تجاهل شرط غير صالح')
            continue
        conditions.append({'metric': metric, 'op': op, 'value': int(value) if value == int(value) else value})

    sort_ok = set(allowed) | {'name'} | ({'month'} if group_by == 'month' else set())
    sort_by = _s('sort_by') if _s('sort_by') in sort_ok else None
    if sort_by is None:
        sort_by = 'month' if group_by == 'month' else next((m for m in metrics if m != 'people'), 'name')
    default_dir = 'asc' if sort_by in ('name', 'month') else 'desc'
    sort_dir = _s('sort_dir') if _s('sort_dir') in ('asc', 'desc') else default_dir

    limit = _int_or_none(raw.get('limit'), 1, MAX_LIMIT) or DEFAULT_LIMIT
    title = str(raw.get('title') or '').strip()[:80]

    return {
        'subject': subject, 'group_by': group_by, 'metrics': metrics,
        'date_from': d_from.isoformat() if d_from else None,
        'date_to': d_to.isoformat() if d_to else None,
        'circles': circle_ids,
        'name_contains': str(raw.get('name_contains') or '').strip()[:60],
        'age_min': age_min, 'age_max': age_max,
        'monthly_columns': bool(raw.get('monthly_columns')) and group_by == 'person',
        'conditions': conditions, 'sort_by': sort_by, 'sort_dir': sort_dir,
        'limit': limit, 'title': title,
    }, warns


def describe_spec(spec, circles, period=None):
    """جملة «كيف فهمتُ سؤالك» تُبنى من المواصفة المنظَّفة (لا من كلام النموذج)."""
    subject = spec['subject']
    names = {c['id']: c['name'] for c in circles}
    parts = ['الطلاب' if subject == 'students' else 'الأساتذة', GROUPS[spec['group_by']]]
    if period:
        parts.append(f'الفترة: من {period[0]} إلى {period[1]}' + ('' if spec['date_from'] or spec['date_to'] else ' (كل الفترة)'))
    if spec['circles']:
        parts.append('الحلقات: ' + '، '.join(names.get(i, str(i)) for i in spec['circles']))
    if spec['name_contains']:
        parts.append(f'الاسم يحوي «{spec["name_contains"]}»')
    if spec['age_min'] is not None or spec['age_max'] is not None:
        a = f'من {spec["age_min"]} ' if spec['age_min'] is not None else ''
        b = f'إلى {spec["age_max"]}' if spec['age_max'] is not None else ''
        parts.append(f'العمر {a}{b}'.strip())
    for c in spec['conditions']:
        parts.append(f'{metric_label(c["metric"], subject)} {OPS[c["op"]]} {c["value"]}')
    sort_name = 'الاسم' if spec['sort_by'] == 'name' else ('الشهر' if spec['sort_by'] == 'month' else metric_label(spec['sort_by'], subject))
    parts.append(f'الترتيب: {sort_name} {"تصاعدياً" if spec["sort_dir"] == "asc" else "تنازلياً"}')
    if spec['group_by'] != 'month':
        parts.append(f'أول {spec["limit"]}')
    return ' · '.join(parts)


# ───────────────────────── مصادر البيانات ─────────────────────────

class DjangoSource:
    """يقرأ البيانات الفعلية: الإحصائيات من محرّك صفحة الإحصائيات (مع كاشه) والبقية من ORM/الكاش."""

    def today(self):
        from django.utils import timezone
        return timezone.localdate()

    def circles(self):
        from . import cache_utils
        return [{'id': c['id'], 'name': c['name']} for c in cache_utils.circles()]

    def student_circles(self):
        from . import cache_utils
        return {sid: cid for sid, _name, cid, _cname in cache_utils.students_index()['rows']}

    def stats(self, subject, start, end, age_min, age_max):
        """يعيد {people, month_cols, start, end} — نفس أرقام صفحة الإحصائيات لكامل المسجد."""
        from django.http import HttpRequest, QueryDict
        from . import views
        params = {'who': 'students' if subject == 'students' else 'staff'}
        if start:
            params['from'] = start.isoformat()
        if end:
            params['to'] = end.isoformat()
        if subject == 'students':
            if age_min is not None:
                params['age_min'] = str(age_min)
            if age_max is not None:
                params['age_max'] = str(age_max)
        req = HttpRequest()
        req.method = 'GET'
        req.GET = QueryDict('&'.join(f'{k}={v}' for k, v in params.items()))
        ctx = views._stats_context(req, paginate=False)
        st = ctx['students_stats'] if subject == 'students' else ctx['staff_stats']
        return {'people': st['people'] if st else [], 'month_cols': st['month_cols'] if st else [],
                'start': ctx['start'], 'end': ctx['end']}

    def recitations(self, start, end, student_ids):
        from .models import Recitation
        return list(Recitation.objects.filter(date__gte=start, date__lte=end, student_id__in=student_ids)
                    .order_by().values_list('student_id', 'date', 'from_surah', 'from_ayah', 'to_surah', 'to_ayah'))

    def sabr(self, start, end, student_ids):
        from .models import Sabr
        return list(Sabr.objects.filter(date__gte=start, date__lte=end, student_id__in=student_ids)
                    .order_by().values_list('student_id', 'date'))


# ───────────────────────── التنفيذ ─────────────────────────

def _month_key(d):
    return f'{d.year:04d}-{d.month:02d}'


def _rate(present, late, sessions, excused):
    base = sessions - excused
    return round((present + late) / base * 100) if base > 0 else None


def _cmp(op, a, b):
    if a is None:
        return False
    return {'>': a > b, '>=': a >= b, '<': a < b, '<=': a <= b, '==': a == b}[op]


def _empty_vals():
    return {k: 0 for k in SUM_KEYS}


def run_spec(spec, source=None):
    """ينفّذ مواصفة منظَّفة ويعيد النتيجة الجاهزة للعرض/التصدير (راجع بنية result في الأسفل)."""
    from . import quran
    source = source or DjangoSource()
    subject, group_by = spec['subject'], spec['group_by']
    circles = source.circles()
    cname = {c['id']: c['name'] for c in circles}
    notes = []

    base = source.stats(subject, _iso(spec['date_from']), _iso(spec['date_to']), spec['age_min'], spec['age_max'])
    people, month_cols = list(base['people']), list(base['month_cols'])
    p_start, p_end = base['start'], base['end']

    # ── فلاتر ما بعد الحساب (الحلقة = الحلقة الحالية للطالب) ──
    stu_circle = source.student_circles() if subject == 'students' else {}
    if spec['circles']:
        wanted = set(spec['circles'])
        people = [p for p in people if stu_circle.get(p['id']) in wanted]
        notes.append('فلتر الحلقة يعتمد على الحلقة الحالية للطالب.')
    if spec['name_contains']:
        words = norm_ar(spec['name_contains']).split()
        people = [p for p in people if all(w in norm_ar(p['name']) for w in words)]

    # ── السبر/التسميع ──
    needed = set(spec['metrics']) | {c['metric'] for c in spec['conditions']} | {spec['sort_by']}
    rec = {}                      # student_id → {'recitations', 'ayahs', 'months': {key: [n, ayahs]}}
    sabr_by_month = {}            # student_id → {key: n}
    ids = {p['id'] for p in people}
    if subject == 'students' and ids and needed & {'recitations', 'ayahs'}:
        for sid, d, fs, fa, ts, ta in source.recitations(p_start, p_end, ids):
            n = quran.safe_ayah_span(fs, fa, ts, ta)
            e = rec.setdefault(sid, {'recitations': 0, 'ayahs': 0, 'months': {}})
            e['recitations'] += 1
            e['ayahs'] += n
            m = e['months'].setdefault(_month_key(d), [0, 0])
            m[0] += 1
            m[1] += n
    if subject == 'students' and ids and group_by == 'month' and 'sabr' in needed:
        for sid, d in source.sabr(p_start, p_end, ids):
            sabr_by_month.setdefault(sid, {})
            k = _month_key(d)
            sabr_by_month[sid][k] = sabr_by_month[sid].get(k, 0) + 1

    def person_vals(p):
        v = {'present': p['present'], 'late': p['late'], 'absent': p['absent'], 'excused': p['excused'],
             'unrecorded': p['unrecorded'], 'sessions': p['expected'], 'sabr': p.get('sabr', 0),
             'recitations': rec.get(p['id'], {}).get('recitations', 0), 'ayahs': rec.get(p['id'], {}).get('ayahs', 0)}
        v['rate'] = p['rate']
        return v

    def finish(vals, people_count=None):
        vals['rate'] = _rate(vals['present'], vals['late'], vals['sessions'], vals['excused'])
        if people_count is not None:
            vals['people'] = people_count
        return vals

    rows = []                     # كل صف: {'name', 'circle', 'key', 'vals', 'monthly'}
    if group_by == 'person':
        for p in people:
            cid = stu_circle.get(p['id'])
            rows.append({'name': p['name'], 'circle': cname.get(cid, p.get('sub') or '') if subject == 'students' else '',
                         'key': p['name'], 'vals': person_vals(p), 'monthly': p.get('months') or []})
    elif group_by == 'circle':
        groups = {}
        for p in people:
            cid = stu_circle.get(p['id'])
            g = groups.setdefault(cid, {'vals': _empty_vals(), 'n': 0})
            for k, v in person_vals(p).items():
                if k != 'rate':
                    g['vals'][k] += v
            g['n'] += 1
        for cid, g in groups.items():
            rows.append({'name': cname.get(cid, 'بلا حلقة'), 'circle': '', 'key': cname.get(cid, ''),
                         'vals': finish(g['vals'], g['n']), 'monthly': []})
    else:                         # month
        for i, col in enumerate(month_cols):
            vals, n = _empty_vals(), 0
            for p in people:
                months = p.get('months') or []
                cell = months[i] if i < len(months) else None
                if cell:
                    n += 1
                    vals['present'] += cell['present']
                    vals['late'] += cell['late']
                    vals['absent'] += cell['absent']
                    vals['excused'] += cell['excused']
                    vals['unrecorded'] += cell['unrecorded']
                    vals['sessions'] += cell['expected']
                vals['sabr'] += sabr_by_month.get(p['id'], {}).get(col['key'], 0)
                mr = rec.get(p['id'], {}).get('months', {}).get(col['key'])
                if mr:
                    vals['recitations'] += mr[0]
                    vals['ayahs'] += mr[1]
            rows.append({'name': col['label'], 'circle': '', 'key': col['key'], 'vals': finish(vals, n), 'monthly': []})

    # ── الشروط ──
    for c in spec['conditions']:
        rows = [r for r in rows if _cmp(c['op'], r['vals'].get(c['metric']), c['value'])]

    # ── الإجمالي (قبل تطبيق الحد) ──
    summary = _summarize(rows, group_by, people, month_cols)

    # ── الفرز والحد ──
    def sort_key(r):
        if spec['sort_by'] == 'name':
            return norm_ar(r['name'])
        if spec['sort_by'] == 'month':
            return r['key']
        return r['vals'].get(spec['sort_by'])
    rev = spec['sort_dir'] == 'desc'
    with_val = [r for r in rows if sort_key(r) is not None]
    without = [r for r in rows if sort_key(r) is None]
    with_val.sort(key=lambda r: norm_ar(r['name']))              # ترتيب ثانوي ثابت
    with_val.sort(key=sort_key, reverse=rev)
    ordered = with_val + without
    total_rows = len(ordered)
    shown = ordered if group_by == 'month' else ordered[:spec['limit']]

    # ── الأعمدة ──
    cols = []
    name_label = {'person': 'الطالب' if subject == 'students' else 'الأستاذ', 'circle': 'الحلقة', 'month': 'الشهر'}[group_by]
    cols.append({'key': 'name', 'label': name_label, 'kind': 'text'})
    if group_by == 'person' and subject == 'students':
        cols.append({'key': 'circle', 'label': 'الحلقة', 'kind': 'text'})
    for m in spec['metrics']:
        cols.append({'key': m, 'label': metric_label(m, subject), 'kind': METRICS[m][1]})
    if spec['monthly_columns']:
        for col in month_cols:
            cols.append({'key': 'm_' + col['key'], 'label': 'متوسط ' + col['label'], 'kind': 'pct'})

    def out_row(r):
        line = [r['name']]
        if group_by == 'person' and subject == 'students':
            line.append(r['circle'])
        line += [r['vals'].get(m) for m in spec['metrics']]
        if spec['monthly_columns']:
            line += [(c['rate'] if c else None) for c in (r['monthly'] + [None] * len(month_cols))[:len(month_cols)]]
        return line

    out_rows = [out_row(r) for r in shown]
    summary_row = None
    if summary and total_rows:
        label = f'الإجمالي ({total_rows})'
        line = [label] + (['—'] if group_by == 'person' and subject == 'students' else [])
        line += [summary['vals'].get(m) for m in spec['metrics']]
        if spec['monthly_columns']:
            line += summary['monthly'][:len(month_cols)] + [None] * (len(month_cols) - len(summary['monthly']))
        summary_row = line

    if spec['group_by'] != 'month' and total_rows > len(shown):
        notes.append(f'عُرض أول {len(shown)} من {total_rows} صفاً (الإجمالي أسفل الجدول يشمل الكل).')
    notes.append('نسبة الحضور = (حاضر + متأخر) ÷ (أيام الدوام − بإذن)؛ والأيام غير المسجَّلة تُحسب غياباً.')

    understood = describe_spec(spec, circles, (p_start.isoformat(), p_end.isoformat()))
    return {
        'title': spec['title'] or _auto_title(spec),
        'understood': understood,
        'columns': cols, 'rows': out_rows, 'summary': summary_row,
        'row_count': total_rows, 'truncated': total_rows > len(shown),
        'period': [p_start.isoformat(), p_end.isoformat()],
        'notes': notes,
    }


def _auto_title(spec):
    who = 'الطلاب' if spec['subject'] == 'students' else 'الأساتذة'
    return f'إحصائيات {who} — {GROUPS[spec["group_by"]]}'


def _summarize(rows, group_by, people, month_cols):
    """الإجمالي: يجمع قيم الصفوف المتبقية ويعيد حساب النسبة من المجاميع (لا متوسط نسب)."""
    if not rows:
        return None
    vals = _empty_vals()
    for r in rows:
        for k in SUM_KEYS:
            vals[k] += r['vals'].get(k, 0) or 0
    vals['rate'] = _rate(vals['present'], vals['late'], vals['sessions'], vals['excused'])
    if group_by == 'person':
        vals['people'] = len(rows)
    elif group_by == 'circle':
        vals['people'] = sum(r['vals'].get('people', 0) for r in rows)
    else:
        vals['people'] = len({p['id'] for p in people})
    monthly = []
    if group_by == 'person' and month_cols:
        for i in range(len(month_cols)):
            s = {'present': 0, 'late': 0, 'sessions': 0, 'excused': 0}
            for r in rows:
                c = r['monthly'][i] if i < len(r['monthly']) else None
                if c:
                    s['present'] += c['present']
                    s['late'] += c['late']
                    s['sessions'] += c['expected']
                    s['excused'] += c['excused']
            monthly.append(_rate(s['present'], s['late'], s['sessions'], s['excused']))
    return {'vals': vals, 'monthly': monthly}


# ───────────────────────── الاتصال بالنموذج ─────────────────────────

API_URL = 'https://api.anthropic.com/v1/messages'
TOOL_NAME = 'build_query'

SYSTEM_PROMPT = """أنت مترجم أسئلة لنظام إحصائيات حضور حلقات القرآن في «مسجد طه». مهمتك الوحيدة: تحويل سؤال المستخدم إلى مواصفة استعلام منظّمة عبر الأداة build_query. لا تجب عن السؤال بنص، ولا تكتب SQL، ولا تخترع بيانات.

تاريخ اليوم: {today} ({weekday}).
الحلقات الموجودة (استخدم الأسماء حرفياً في الحقل circles): {circles}

المقاييس (metrics):
- rate: نسبة الحضور % = (حاضر + متأخر) ÷ (أيام الدوام − بإذن)؛ غير المسجَّل يُحتسب غياباً.
- present / late / absent / excused: عدد أيام الحاضر / المتأخر / الغائب / الغائب بإذن.
- unrecorded: أيام لم يُسجَّل فيها حضور للفرد. sessions: أيام الدوام المتوقعة.
- sabr: مرات السبر، recitations: مرات التسميع، ayahs: مجموع الآيات المُسمَّعة (للطلاب فقط).
- people: عدد الطلاب/الأساتذة (يُستخدم فقط مع group_by = circle أو month).

التجميع (group_by): person = صف لكل طالب/أستاذ، circle = صف لكل حلقة، month = صف لكل شهر.

قواعد:
1) إن لم تُذكر فترة فاترك date_from و date_to فارغين (= كل الفترة). وإن ذُكرت نسبياً (هذا الشهر، الشهر الماضي، آخر شهرين، هذا العام…) فاحسب التواريخ من تاريخ اليوم بصيغة YYYY-MM-DD.
2) «الأكثر غياباً» ⇒ sort_by=absent و sort_dir=desc؛ «الأقل حضوراً» ⇒ sort_by=rate و sort_dir=asc؛ «الأعلى حضوراً» ⇒ rate تنازلياً.
3) العتبات تُكتب في conditions، مثل «غاب أكثر من 3 مرات» ⇒ [{{"metric":"absent","op":">","value":3}}].
4) «لكل حلقة» أو «رتّب الحلقات» ⇒ group_by=circle. «شهرياً» ⇒ group_by=month، أو monthly_columns=true إن طُلب جدول طلاب بعمود لكل شهر.
5) الأساتذة أو الكادر ⇒ subject=teachers. الطلاب هو الافتراضي.
6) إن سُئلت عن طالب محدد فاستخدم name_contains. وإن طُلب «أعلى N» فاضبط limit=N.
7) إن كان السؤال خارج نطاق إحصائيات الحضور والسبر والتسميع، أو يطلب تعديل/حذف بيانات، فاستدعِ الأداة مع unsupported=true وسبب موجز بالعربية في reason.

أمثلة:
- «من الأكثر غياباً هذا الشهر؟» ⇒ subject=students, group_by=person, metrics=[absent, rate], date_from=أول الشهر الحالي, date_to=اليوم, sort_by=absent, sort_dir=desc, limit=20
- «رتّب الحلقات بنسبة الحضور» ⇒ group_by=circle, metrics=[rate, present, absent], sort_by=rate, sort_dir=desc
- «نسبة حضور الأساتذة شهرياً» ⇒ subject=teachers, group_by=month, metrics=[rate, present, absent]
- «كم آية سمّع الطلاب في حلقة أبي هذا الشهر؟» ⇒ group_by=person, metrics=[recitations, ayahs], circles=[«حلقة أبي»], sort_by=ayahs, sort_dir=desc"""


def build_tool_schema():
    metric_enum = list(METRICS)
    return {
        'name': TOOL_NAME,
        'description': 'يبني مواصفة استعلام إحصائي منظّمة من سؤال المستخدم.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'unsupported': {'type': 'boolean', 'description': 'true إن كان السؤال خارج نطاق الإحصائيات المدعومة'},
                'reason': {'type': 'string', 'description': 'سبب عدم الدعم (بالعربية)'},
                'subject': {'type': 'string', 'enum': list(BOTH)},
                'group_by': {'type': 'string', 'enum': list(GROUPS)},
                'metrics': {'type': 'array', 'items': {'type': 'string', 'enum': metric_enum}},
                'date_from': {'type': ['string', 'null'], 'description': 'YYYY-MM-DD أو null'},
                'date_to': {'type': ['string', 'null'], 'description': 'YYYY-MM-DD أو null'},
                'circles': {'type': 'array', 'items': {'type': 'string'}, 'description': 'أسماء حلقات حرفياً'},
                'name_contains': {'type': ['string', 'null']},
                'age_min': {'type': ['integer', 'null']},
                'age_max': {'type': ['integer', 'null']},
                'monthly_columns': {'type': 'boolean'},
                'conditions': {'type': 'array', 'items': {
                    'type': 'object',
                    'properties': {'metric': {'type': 'string', 'enum': metric_enum},
                                   'op': {'type': 'string', 'enum': list(OPS)},
                                   'value': {'type': 'number'}},
                    'required': ['metric', 'op', 'value']}},
                'sort_by': {'type': 'string', 'enum': metric_enum + ['name', 'month']},
                'sort_dir': {'type': 'string', 'enum': ['asc', 'desc']},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_LIMIT},
                'title': {'type': 'string', 'description': 'عنوان قصير للجدول بالعربية'},
            },
            'required': ['subject', 'group_by', 'metrics'],
        },
    }


_WEEKDAYS = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']


def build_request_body(question, today, circle_names, model):
    return {
        'model': model,
        'max_tokens': 1024,
        'system': SYSTEM_PROMPT.format(today=today.isoformat(), weekday=_WEEKDAYS[today.weekday()],
                                       circles='، '.join(circle_names) or '(لا توجد حلقات)'),
        'messages': [{'role': 'user', 'content': question}],
        'tools': [build_tool_schema()],
        'tool_choice': {'type': 'tool', 'name': TOOL_NAME},
    }


def ask_llm(question, today, circle_names, api_key, model, http=None, timeout=30):
    """يرسل السؤال (دون أي بيانات طلاب) ويعيد مواصفة خام. يرفع AssistantError برسالة عربية."""
    if not api_key:
        raise AssistantError('ميزة السؤال بالذكاء الاصطناعي غير مفعّلة. أضف المتغيّر ANTHROPIC_API_KEY في إعدادات الخادم '
                             '(يمكنك الآن استخدام «تعديل التفسير» لبناء الاستعلام يدوياً).', 'no_key')
    if http is None:
        import requests as http
    try:
        resp = http.post(API_URL, timeout=timeout, headers={
            'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json',
        }, json=build_request_body(question, today, circle_names, model))
    except Exception as e:                       # noqa: BLE001 — مهلة/شبكة
        logger.warning('تعذّر الاتصال بخدمة الذكاء الاصطناعي: %s', e)
        raise AssistantError('تعذّر الاتصال بخدمة الذكاء الاصطناعي الآن. حاول بعد قليل.', 'network')
    status = getattr(resp, 'status_code', 0)
    if status in (401, 403):
        raise AssistantError('مفتاح الذكاء الاصطناعي غير صالح أو منتهٍ. راجع ANTHROPIC_API_KEY.', 'auth')
    if status == 429:
        raise AssistantError('الخدمة مشغولة حالياً (تجاوز حدّ الطلبات). جرّب بعد دقيقة.', 'rate')
    if status >= 400:
        logger.warning('خطأ من خدمة الذكاء الاصطناعي: %s %s', status, getattr(resp, 'text', '')[:300])
        raise AssistantError('تعذّر فهم السؤال بسبب خطأ في الخدمة. حاول مجدداً.', 'api')
    try:
        data = resp.json()
    except ValueError:
        raise AssistantError('استجابة غير مفهومة من الخدمة.', 'api')
    for block in data.get('content') or []:
        if block.get('type') == 'tool_use' and block.get('name') == TOOL_NAME and isinstance(block.get('input'), dict):
            return block['input']
    raise AssistantError('لم أتمكن من تحويل السؤال إلى استعلام. أعد صياغته أو استخدم «تعديل التفسير».', 'parse')


# ───────────────────────── بيانات واجهة المستخدم ─────────────────────────

def ui_meta(circles):
    """ما تحتاجه واجهة «تعديل التفسير» لبناء النموذج (قوائم مسموحة + أسماء عربية)."""
    return {
        'metrics': {s: [{'key': k, 'label': metric_label(k, s), 'kind': METRICS[k][1]} for k in allowed_metrics(s, 'circle')]
                    for s in BOTH},
        'groups': [{'key': k, 'label': v} for k, v in GROUPS.items()],
        'ops': [{'key': k, 'label': v} for k, v in OPS.items()],
        'circles': circles,
        'subjects': [{'key': 'students', 'label': 'الطلاب'}, {'key': 'teachers', 'label': 'الأساتذة'}],
        'max_limit': MAX_LIMIT, 'max_conditions': MAX_CONDITIONS,
    }


def spec_to_json(spec):
    return json.dumps(spec, ensure_ascii=False, separators=(',', ':'))
