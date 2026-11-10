"""
استيراد ملف Excel صادر مسبقاً عن النظام (ملف «إرسال البيانات إلى تلغرام» أو «تنزيل نسخة Excel»).

وضعان:
  - merge   (دمج): يضيف ما ليس موجوداً فقط، ولا يحذف أو يكتب فوق أي سجل حالي
                   (يُكمِل فقط الحقول الفارغة لدى السجلات الموجودة: الهاتف، الملاحظات، تاريخ الميلاد…).
  - replace (استبدال): يمسح كل البيانات ثم يستورد الملف كاملاً.

المطابقة:
  - الملفات الحديثة تحوي أعمدة «المعرّف» في آخر كل ورقة ⇒ مطابقة دقيقة حتى مع تكرار الأسماء
    (حلقتان بنفس الاسم، طالب انتقل بين حلقات…).
  - الملفات القديمة (بدون معرّفات) تُطابَق بالأسماء: الأستاذ/الحلقة/الدورة بالاسم، والطالب بـ (الاسم + الحلقة).

أوراق الملف (بنفس أسماء التصدير؛ الأعمدة بعد «…» اختيارية):
  الأساتذة:      م | اسم الأستاذ | رقم الهاتف | المعرّف
  الحلقات:       م | اسم الحلقة | الأستاذ | عدد الطلاب | الوصف | ترتيب العرض | المعرّف | معرّف الأستاذ
  الطلاب:        م | اسم الطالب | الحلقة | الهاتف | ملاحظات | تاريخ الانضمام | تاريخ الميلاد | المعرّف | معرّف الحلقة
  حضور الحلقات:  التاريخ | الحلقة | النوع | الاسم | الحالة | معرّف الشخص | معرّف الحلقة
  الدورات:       م | اسم الدورة | الأساتذة | عدد الطلاب | الوصف | المعرّف | معرّفات الأساتذة | معرّفات الطلاب
  حضور الدورات:  التاريخ | الدورة | النوع | الاسم | الحالة | معرّف الشخص | معرّف الدورة
  التفقد العام:  التاريخ | اسم الأستاذ | الحالة | معرّف الأستاذ
  السبر:         التاريخ | اسم الطالب | الحلقة | التفاصيل | معرّف الطالب
"""
import datetime

from django.db import connection, transaction

from .models import (
    Teacher, Circle, Student, Attendance, TeacherAttendance,
    Course, CourseAttendance, CourseTeacherAttendance, TeacherDailyAttendance, Sabr,
)

_STATUS_MAP = {display: value for value, display in Attendance.STATUS_CHOICES}


def _status(arabic):
    v = str(arabic or '').strip()
    return _STATUS_MAP.get(v, v if v in dict(Attendance.STATUS_CHOICES) else 'present')


def _clean(val):
    s = str(val).strip() if val is not None else ''
    return '' if s in ('—', 'None', '') else s


def _cell(row, i):
    return row[i] if row is not None and len(row) > i else None


def _xid(row, i):
    """معرّف التصدير (رقم صحيح) أو None."""
    v = _cell(row, i)
    try:
        return int(v) if v not in (None, '', '—') else None
    except (TypeError, ValueError):
        return None


def _ids(row, i):
    out = []
    for part in str(_cell(row, i) or '').split(','):
        try:
            out.append(int(part))
        except ValueError:
            pass
    return out


def _parse_date(val):
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    s = _clean(val)[:10]
    if not s:
        return None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:                                             # مثل 2026-8-9
        y, m, d = (int(x) for x in s.replace('/', '-').split('-'))
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def _reset_pg_sequences():
    if 'postgresql' not in connection.settings_dict.get('ENGINE', ''):
        return
    tables = [
        'halaqat_teacher', 'halaqat_circle', 'halaqat_student', 'halaqat_attendance',
        'halaqat_teacherattendance', 'halaqat_course', 'halaqat_courseattendance',
        'halaqat_courseteacherattendance', 'halaqat_teacherdailyattendance', 'halaqat_sabr',
    ]
    with connection.cursor() as cur:
        for t in tables:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM \"{t}\"), 1))"
            )


def import_workbook(wb, mode='merge'):
    """يستورد Workbook (openpyxl) ويعيد [(البيان، العدد المضاف)]. يرفع استثناءً عند الفشل (مع التراجع)."""
    replace = mode == 'replace'

    def sheet(name):
        if name not in wb.sheetnames:
            return []
        return [r for r in wb[name].iter_rows(min_row=2, values_only=True) if r and any(c is not None for c in r)]

    results = []
    with transaction.atomic():
        if replace:
            TeacherDailyAttendance.objects.all().delete()
            CourseTeacherAttendance.objects.all().delete()
            CourseAttendance.objects.all().delete()
            Course.objects.all().delete()
            TeacherAttendance.objects.all().delete()
            Attendance.objects.all().delete()
            Sabr.objects.all().delete()
            Student.objects.all().delete()
            Circle.objects.all().delete()
            Teacher.objects.all().delete()

        def existing_match(model, xid, **same):
            """في وضع الدمج: سجل موجود بنفس المعرّف ونفس الاسم ⇒ هو نفسه (ملف من نفس القاعدة)."""
            if replace or xid is None:
                return None
            return model.objects.filter(pk=xid, **same).first()

        # ════════ الأساتذة ════════
        teachers = {}                          # name → Teacher (أول تطابق)
        for t in Teacher.objects.order_by('id'):
            teachers.setdefault(t.name, t)
        t_by_x = {}                            # معرّف التصدير → Teacher
        added = 0
        for row in sheet('الأساتذة'):
            name = _clean(_cell(row, 1))
            if not name:
                continue
            xid, phone = _xid(row, 3), _clean(_cell(row, 2))
            t = existing_match(Teacher, xid, name=name)
            if t is None and not (replace and xid is not None):
                t = teachers.get(name)
            if t is None:
                t = Teacher.objects.create(name=name, phone=phone)
                teachers.setdefault(name, t)
                added += 1
            elif phone and not t.phone:
                t.phone = phone
                t.save(update_fields=['phone'])
            if xid is not None:
                t_by_x[xid] = t
        results.append(('الأساتذة', added))

        def teacher_ref(xid=None, name=None):
            if xid is not None and xid in t_by_x:
                return t_by_x[xid]
            name = _clean(name)
            if not name:
                return None
            if name not in teachers:
                teachers[name] = Teacher.objects.create(name=name)
            return teachers[name]

        # ════════ الحلقات ════════
        circles = {}
        for c in Circle.objects.order_by('id'):
            circles.setdefault(c.name, c)
        c_by_x = {}
        added = 0
        for row in sheet('الحلقات'):
            name = _clean(_cell(row, 1))
            if not name:
                continue
            xid = _xid(row, 6)
            c = existing_match(Circle, xid, name=name)
            if c is None and not (replace and xid is not None):
                c = circles.get(name)
            teacher = teacher_ref(_xid(row, 7), _cell(row, 2))
            if c is None:
                try:
                    order = int(_cell(row, 5) or 0)
                except (TypeError, ValueError):
                    order = 0
                c = Circle.objects.create(name=name, teacher=teacher,
                                          description=_clean(_cell(row, 4)), display_order=order)
                circles.setdefault(name, c)
                added += 1
            elif c.teacher_id is None and teacher:
                c.teacher = teacher
                c.save(update_fields=['teacher'])
            if xid is not None:
                c_by_x[xid] = c
        results.append(('الحلقات', added))

        def circle_ref(xid=None, name=None, create=False):
            if xid is not None and xid in c_by_x:
                return c_by_x[xid]
            name = _clean(name)
            if not name:
                return None
            if name not in circles and create:
                circles[name] = Circle.objects.create(name=name)
            return circles.get(name)

        # ════════ الطلاب ════════
        students = {}                          # (name, circle_id) → Student
        students_by_name = {}
        for s in Student.objects.order_by('id'):
            students.setdefault((s.name, s.circle_id), s)
            students_by_name.setdefault(s.name, s)
        s_by_x = {}
        added = 0
        for row in sheet('الطلاب'):
            name = _clean(_cell(row, 1))
            circle = circle_ref(_xid(row, 8), _cell(row, 2), create=True)
            if not name or not circle:
                continue
            xid = _xid(row, 7)
            phone, notes = _clean(_cell(row, 3)), _clean(_cell(row, 4))
            birth = _parse_date(_cell(row, 6))
            s = existing_match(Student, xid, name=name)
            if s is None and not (replace and xid is not None):
                s = students.get((name, circle.id))
            if s is None:
                s = Student.objects.create(name=name, circle=circle, phone=phone, notes=notes, birth_date=birth)
                joined = _parse_date(_cell(row, 5))
                if joined:
                    Student.objects.filter(pk=s.pk).update(joined_at=datetime.datetime(
                        joined.year, joined.month, joined.day, tzinfo=datetime.timezone.utc))
                students.setdefault((name, circle.id), s)
                students_by_name.setdefault(name, s)
                added += 1
            else:
                changed = [f for f, v in (('phone', phone), ('notes', notes), ('birth_date', birth))
                           if v and not getattr(s, f)]
                for f in changed:
                    setattr(s, f, {'phone': phone, 'notes': notes, 'birth_date': birth}[f])
                if changed:
                    s.save(update_fields=changed + ['updated_at'])
            if xid is not None:
                s_by_x[xid] = s
        results.append(('الطلاب', added))

        def student_ref(xid=None, name=None, circle=None):
            if xid is not None and xid in s_by_x:
                return s_by_x[xid]
            name = _clean(name)
            if not name:
                return None
            if circle is not None and (name, circle.id) in students:
                return students[(name, circle.id)]
            return students_by_name.get(name)       # طالب انتقل لاحقاً إلى حلقة أخرى

        # ════════ السبر ════════
        existing = set(Sabr.objects.values_list('student_id', 'date'))
        objs = []
        for row in sheet('السبر'):
            d = _parse_date(_cell(row, 0))
            s = student_ref(_xid(row, 4), _cell(row, 1), circle_ref(None, _cell(row, 2)))
            if d and s and (s.id, d) not in existing:
                existing.add((s.id, d))
                objs.append(Sabr(student=s, date=d, notes=_clean(_cell(row, 3))))
        Sabr.objects.bulk_create(objs)
        results.append(('السبر', len(objs)))

        # ════════ حضور الحلقات ════════
        att_existing = set(Attendance.objects.values_list('student_id', 'date'))
        tatt_existing = set(TeacherAttendance.objects.values_list('teacher_id', 'circle_id', 'date'))
        att_objs, tatt_objs = [], []
        for row in sheet('حضور الحلقات'):
            d = _parse_date(_cell(row, 0))
            kind = _clean(_cell(row, 2))
            circle = circle_ref(_xid(row, 6), _cell(row, 1))
            if not d or not circle:
                continue
            status = _status(_cell(row, 4))
            if kind == 'طالب':
                s = student_ref(_xid(row, 5), _cell(row, 3), circle)
                if s and (s.id, d) not in att_existing:
                    att_existing.add((s.id, d))
                    att_objs.append(Attendance(student=s, circle=circle, date=d, status=status))
            elif kind == 'أستاذ':
                t = teacher_ref(_xid(row, 5), _cell(row, 3))
                if t and (t.id, circle.id, d) not in tatt_existing:
                    tatt_existing.add((t.id, circle.id, d))
                    tatt_objs.append(TeacherAttendance(teacher=t, circle=circle, date=d, status=status))
        Attendance.objects.bulk_create(att_objs, batch_size=1000)
        TeacherAttendance.objects.bulk_create(tatt_objs, batch_size=1000)
        results.append(('حضور الطلاب في الحلقات', len(att_objs)))
        results.append(('حضور الأساتذة في الحلقات', len(tatt_objs)))

        # ════════ الدورات ════════
        courses = {}
        for c in Course.objects.order_by('id'):
            courses.setdefault(c.name, c)
        k_by_x = {}
        added = 0
        for row in sheet('الدورات'):
            name = _clean(_cell(row, 1))
            if not name:
                continue
            xid = _xid(row, 5)
            c = existing_match(Course, xid, name=name)
            if c is None and not (replace and xid is not None):
                c = courses.get(name)
            if c is None:
                c = Course.objects.create(name=name, description=_clean(_cell(row, 4)))
                courses.setdefault(name, c)
                added += 1
            if xid is not None:
                k_by_x[xid] = c
            t_ids = _ids(row, 6)
            if t_ids:
                c.teachers.add(*[t_by_x[i] for i in t_ids if i in t_by_x])
            else:
                for t_name in str(_cell(row, 2) or '').replace(',', '،').split('،'):
                    t = teacher_ref(None, t_name)
                    if t:
                        c.teachers.add(t)
            s_ids = [s_by_x[i] for i in _ids(row, 7) if i in s_by_x]
            if s_ids:
                c.students.add(*s_ids)
        results.append(('الدورات', added))

        def course_ref(xid=None, name=None):
            if xid is not None and xid in k_by_x:
                return k_by_x[xid]
            return courses.get(_clean(name))

        # ════════ حضور الدورات ════════
        ca_existing = set(CourseAttendance.objects.values_list('student_id', 'course_id', 'date'))
        cta_existing = set(CourseTeacherAttendance.objects.values_list('teacher_id', 'course_id', 'date'))
        ca_objs, cta_objs, enrolled = [], [], {}
        for row in sheet('حضور الدورات'):
            d = _parse_date(_cell(row, 0))
            course = course_ref(_xid(row, 6), _cell(row, 1))
            kind = _clean(_cell(row, 2))
            if not d or not course:
                continue
            status = _status(_cell(row, 4))
            if kind == 'طالب':
                s = student_ref(_xid(row, 5), _cell(row, 3))
                if s:
                    enrolled.setdefault(course, set()).add(s)
                    if (s.id, course.id, d) not in ca_existing:
                        ca_existing.add((s.id, course.id, d))
                        ca_objs.append(CourseAttendance(student=s, course=course, date=d, status=status))
            elif kind == 'أستاذ':
                t = teacher_ref(_xid(row, 5), _cell(row, 3))
                if t and (t.id, course.id, d) not in cta_existing:
                    cta_existing.add((t.id, course.id, d))
                    cta_objs.append(CourseTeacherAttendance(teacher=t, course=course, date=d, status=status))
        CourseAttendance.objects.bulk_create(ca_objs, batch_size=1000)
        CourseTeacherAttendance.objects.bulk_create(cta_objs, batch_size=1000)
        for course, studs in enrolled.items():
            course.students.add(*studs)
        results.append(('حضور الدورات', len(ca_objs) + len(cta_objs)))

        # ════════ التفقد العام ════════
        g_existing = set(TeacherDailyAttendance.objects.values_list('teacher_id', 'date'))
        g_objs = []
        for row in sheet('التفقد العام'):
            d = _parse_date(_cell(row, 0))
            t = teacher_ref(_xid(row, 3), _cell(row, 1))
            if d and t and (t.id, d) not in g_existing:
                g_existing.add((t.id, d))
                g_objs.append(TeacherDailyAttendance(teacher=t, date=d, status=_status(_cell(row, 2))))
        TeacherDailyAttendance.objects.bulk_create(g_objs)
        results.append(('التفقد العام للأساتذة', len(g_objs)))

        _reset_pg_sequences()

    return results
