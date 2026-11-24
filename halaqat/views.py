import csv
import datetime
import io
import json
import logging
import re
from random import randint
import threading
import time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db import transaction
from django.views.decorators.http import require_POST

from . import ai_export, ai_query, cache_utils, quran
from .models import (
    Teacher, Circle, Student, Attendance, TeacherAttendance,
    Course, CourseAttendance, CourseTeacherAttendance, TeacherDailyAttendance, Sabr, Recitation, AssistantQuery,
)
from .forms import CircleForm, StudentForm, CourseForm, WhatsAppAbsentForm, ViewerAccountForm
from .roles import VIEWER_GROUP, is_viewer
from .telegram_utils import send_telegram_message, send_telegram_document_bytes
from .whatsapp_utils import normalize_chat_id, send_whatsapp_text


@login_required
def home(request):
    """
    الصفحة الرئيسية: متابعة تسجيل الحضور اليومي لكل الحلقات والأساتذة
    (هل سُجّل للجميع؟) + ملخص سريع لأعداد الطلاب في ذلك اليوم.
    """
    from collections import Counter
    from django.db.models import Count
    selected_date = _parse_date_param(request)

    circles = cache_utils.circles()          # من الكاش: الحلقات + الأستاذ + عدد الطلاب
    rec_by_circle = Counter(dict(
        Attendance.objects.filter(date=selected_date).values('circle_id').annotate(c=Count('id')).values_list('circle_id', 'c')
    ))
    teacher_done = set(TeacherAttendance.objects.filter(date=selected_date).values_list('teacher_id', 'circle_id'))

    status_counts = Counter(dict(
        Attendance.objects.filter(date=selected_date).values('status').annotate(c=Count('id')).values_list('status', 'c')
    ))

    circle_rows, done_circles = [], 0
    for c in circles:
        recorded = rec_by_circle.get(c['id'], 0)
        teacher_id = c['teacher']['id'] if c['teacher'] else None
        t_ok = (teacher_id, c['id']) in teacher_done if teacher_id else None
        complete = c['students'] > 0 and recorded >= c['students'] and t_ok is not False
        if complete:
            done_circles += 1
        circle_rows.append({
            'circle': c, 'students': c['students'], 'recorded': recorded, 'teacher_ok': t_ok,
            'state': 'ok' if complete else ('part' if recorded or t_ok else 'no'),
        })

    # الأساتذة غير المرتبطين بحلقة/دورة → التفقد العام
    free_teachers = cache_utils.free_teachers()
    general_done = set(TeacherDailyAttendance.objects.filter(date=selected_date).values_list('teacher_id', flat=True))
    teacher_rows = [{'teacher': t, 'ok': t['id'] in general_done} for t in free_teachers]

    # الدورات: تُعرض فقط إن سُجّل فيها شيء في ذلك اليوم (لا جدول ثابت للدورات)
    course_rows = []
    course_rec = Counter(dict(
        CourseAttendance.objects.filter(date=selected_date).values('course_id').annotate(c=Count('id')).values_list('course_id', 'c')
    ))
    if course_rec:
        for co in Course.objects.filter(id__in=course_rec.keys()).annotate(n=Count('students')):
            course_rows.append({'course': co, 'students': co.n, 'recorded': course_rec[co.id],
                                'state': 'ok' if course_rec[co.id] >= co.n else 'part'})

    total_students = sum(c['students'] for c in circles)
    total_recorded = sum(rec_by_circle.values())
    circle_teachers = [r for r in circle_rows if r['teacher_ok'] is not None]
    context = {
        'active_nav': 'home',
        'selected_date': selected_date,
        'today': timezone.localdate(),
        'circle_rows': circle_rows,
        'done_circles': done_circles,
        'all_done': done_circles == len(circles) and all(r['ok'] for r in teacher_rows),
        'teacher_rows': teacher_rows,
        'course_rows': course_rows,
        'teachers_total': len(circle_teachers) + len(teacher_rows),
        'teachers_done': sum(1 for r in circle_teachers if r['teacher_ok']) + sum(1 for r in teacher_rows if r['ok']),
        'counts': {
            'present': status_counts.get('present', 0), 'late': status_counts.get('late', 0),
            'excused': status_counts.get('excused', 0), 'absent': status_counts.get('absent', 0),
            'unrecorded': max(total_students - total_recorded, 0),
        },
        'total_students': total_students,
        'total_recorded': total_recorded,
    }
    return render(request, 'halaqat/home.html', context)


@login_required
def help_page(request):
    return render(request, 'halaqat/help.html', {'active_nav': 'help'})


@login_required
def circles_list(request):
    """بطاقات الحلقات: البيانات الثابتة من الكاش + استعلامان مجمّعان فقط لحضور اليوم."""
    from collections import Counter
    from django.db.models import Count
    circles = cache_utils.circles()
    today = timezone.now().date()

    by_circle = {}
    for row in (Attendance.objects.filter(date=today)
                .values('circle_id', 'status').annotate(c=Count('id'))):
        by_circle.setdefault(row['circle_id'], Counter())[row['status']] += row['c']
    teacher_done = set(TeacherAttendance.objects.filter(date=today).values_list('teacher_id', 'circle_id'))

    circle_cards = []
    for circle in circles:
        cnt = by_circle.get(circle['id'], Counter())
        recorded_students = sum(cnt.values())
        present_today = cnt['present'] + cnt['late']
        counted = recorded_students - cnt['excused']
        rate = None
        if recorded_students and counted:
            rate = round((present_today / counted) * 100)

        # اكتمال التسجيل: كل الطلاب + الأستاذ (إن وُجد)
        total = circle['students']
        recorded = recorded_students
        if circle['teacher']:
            total += 1
            if (circle['teacher']['id'], circle['id']) in teacher_done:
                recorded += 1
        if total == 0:
            card_status = 'empty'
        elif recorded >= total:
            card_status = 'complete'
        else:
            card_status = 'incomplete'

        circle_cards.append({
            'circle': circle,
            'student_count': circle['students'],
            'today_rate': rate,
            'card_status': card_status,
            'progress_total': total,
            'progress_recorded': recorded,
        })

    context = {
        'circle_cards': circle_cards,
        'total_circles': len(circles),
        'total_students': sum(c['students'] for c in circles),
        'today': today,
        'active_nav': 'circles',
    }
    return render(request, 'halaqat/circles_list.html', context)



HISTORY_WEEKS = 4   # عدد الأسابيع السابقة المعروضة مباشرة بجانب كل طالب


def _week_start(d):
    """بداية الأسبوع (السبت)."""
    return d - datetime.timedelta(days=(d.weekday() + 2) % 7)


def _attendance_history(model, scope, student_ids, before_date, weeks=HISTORY_WEEKS):
    """
    حضور آخر `weeks` أسابيع (الأسبوع الحالي + السابقة) قبل التاريخ المحدد، مجمّعاً بالأسابيع.
    أيام كل أسبوع = الأيام التي سُجّل فيها حضور ضمن نفس الحلقة/الدورة.
    scope مثل {'circle': circle} أو {'course': course}.
    يعيد {student_id: {'weeks': [{'start', 'cells': [{'date','status'}]}], 'rate': int|None}}.
    """
    first_week = _week_start(before_date) - datetime.timedelta(days=7 * (weeks - 1))
    dates = sorted(set(
        model.objects.filter(date__gte=first_week, date__lt=before_date, **scope)
        .values_list('date', flat=True)
    ))
    by_student = {}
    if dates:
        for sid, d, st in model.objects.filter(
            date__in=dates, student_id__in=student_ids, **scope
        ).values_list('student_id', 'date', 'status'):
            by_student.setdefault(sid, {})[d] = st

    week_starts = [first_week + datetime.timedelta(days=7 * i) for i in range(weeks)]
    out = {}
    for sid in student_ids:
        recs = by_student.get(sid, {})
        wk = []
        counted = []
        for ws in week_starts:
            cells = [{'date': d, 'status': recs.get(d)} for d in dates if ws <= d < ws + datetime.timedelta(days=7)]
            counted += [c['status'] for c in cells if c['status'] in ('present', 'late', 'absent')]
            wk.append({'start': ws, 'cells': cells})
        rate = round(sum(1 for x in counted if x != 'absent') / len(counted) * 100) if counted else None
        out[sid] = {'weeks': wk, 'rate': rate}
    return out


@login_required
def circle_detail(request, circle_id):
    circle = get_object_or_404(Circle, pk=circle_id)
    students = circle.students.all()

    # تحديد التاريخ المعروض (اليوم افتراضياً، أو من ?date=YYYY-MM-DD)
    date_str = request.GET.get('date')
    if date_str:
        try:
            selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = timezone.now().date()
    else:
        selected_date = timezone.now().date()

    # جلب الحالات الحالية لهذا اليوم
    existing = {
        a.student_id: a.status
        for a in Attendance.objects.filter(circle=circle, date=selected_date)
    }

    history = _attendance_history(Attendance, {'circle': circle}, [s.id for s in students], selected_date)
    student_rows = []
    for student in students:
        student_rows.append({
            'student': student,
            'status': existing.get(student.id, ''),  # فارغ = لم يُسجَّل بعد
            'history': history.get(student.id),
        })

    present_count = sum(1 for s in student_rows if s['status'] == 'present')
    late_count = sum(1 for s in student_rows if s['status'] == 'late')
    absent_count = sum(1 for s in student_rows if s['status'] == 'absent')
    excused_count = sum(1 for s in student_rows if s['status'] == 'excused')

    teacher_status = ''
    if circle.teacher:
        ta = TeacherAttendance.objects.filter(
            teacher=circle.teacher, circle=circle, date=selected_date
        ).first()
        teacher_status = ta.status if ta else ''

    # للتنقل بين الحلقات دون الخروج من الصفحة (أزرار سابق/تالي + قائمة منسدلة)
    all_circles = cache_utils.circles()
    ids = [c['id'] for c in all_circles]
    idx = ids.index(circle.id) if circle.id in ids else None
    prev_circle = all_circles[idx - 1] if idx is not None and idx > 0 else None
    next_circle = all_circles[idx + 1] if idx is not None and idx < len(all_circles) - 1 else None

    context = {
        'circle': circle,
        'student_rows': student_rows,
        'selected_date': selected_date,
        'present_count': present_count,
        'late_count': late_count,
        'absent_count': absent_count,
        'excused_count': excused_count,
        'attendance_rate_30d': circle.attendance_rate(30),
        'teacher_status': teacher_status,
        'all_circles': all_circles,
        'prev_circle': prev_circle,
        'next_circle': next_circle,
        'active_nav': 'circles',
    }
    return render(request, 'halaqat/circle_detail.html', context)


@login_required
@require_POST
def save_attendance(request, circle_id):
    """حفظ فوري لحالة حضور طالب أو الأستاذ عبر AJAX - بدون زر حفظ."""
    circle = get_object_or_404(Circle, pk=circle_id)
    kind = request.POST.get('kind', 'student')
    entity_id = request.POST.get('entity_id')
    status = request.POST.get('status')
    date_str = request.POST.get('date')

    if status not in dict(Attendance.STATUS_CHOICES):
        return JsonResponse({'ok': False, 'error': 'حالة غير صالحة'}, status=400)

    try:
        selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'تاريخ غير صالح'}, status=400)

    if kind == 'teacher':
        if not circle.teacher or str(circle.teacher.id) != str(entity_id):
            return JsonResponse({'ok': False, 'error': 'لا يوجد أستاذ مطابق لهذه الحلقة'}, status=400)
        TeacherAttendance.objects.update_or_create(
            teacher=circle.teacher, circle=circle, date=selected_date,
            defaults={'status': status},
        )
    else:
        student = get_object_or_404(Student, pk=entity_id, circle=circle)
        Attendance.objects.update_or_create(
            student=student, date=selected_date,
            defaults={'circle': circle, 'status': status},
        )

    records = Attendance.objects.filter(circle=circle, date=selected_date)
    counts = {
        'present': records.filter(status='present').count(),
        'late': records.filter(status='late').count(),
        'absent': records.filter(status='absent').count(),
        'excused': records.filter(status='excused').count(),
    }
    return JsonResponse({'ok': True, 'counts': counts})


# ============================================================
#  الدورات والدروس الإضافية (فئة محددة من الطلاب، حضور مستقل)
# ============================================================

@login_required
def courses_list(request):
    courses = Course.objects.prefetch_related('teachers', 'students')
    today = timezone.now().date()

    course_cards = []
    for course in courses:
        total_students = course.student_count
        today_records = CourseAttendance.objects.filter(course=course, date=today)
        present_today = today_records.filter(status__in=['present', 'late']).count()
        rate = None
        if today_records.exists():
            counted = today_records.exclude(status='excused').count()
            rate = round((present_today / counted) * 100) if counted else None

        progress = course.attendance_progress(today)
        if progress['total'] == 0:
            card_status = 'empty'
        elif progress['complete']:
            card_status = 'complete'
        else:
            card_status = 'incomplete'

        course_cards.append({
            'course': course,
            'student_count': total_students,
            'today_rate': rate,
            'card_status': card_status,
        })

    context = {
        'course_cards': course_cards,
        'total_courses': courses.count(),
        'today': today,
        'active_nav': 'courses',
    }
    return render(request, 'halaqat/courses_list.html', context)


@login_required
def course_detail(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    students = course.students.select_related('circle').order_by('name')

    date_str = request.GET.get('date')
    if date_str:
        try:
            selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = timezone.now().date()
    else:
        selected_date = timezone.now().date()

    existing = {
        a.student_id: a.status
        for a in CourseAttendance.objects.filter(course=course, date=selected_date)
    }

    students = list(students)
    history = _attendance_history(CourseAttendance, {'course': course}, [s.id for s in students], selected_date)
    student_rows = []
    for student in students:
        student_rows.append({
            'student': student,
            'status': existing.get(student.id, ''),
            'history': history.get(student.id),
        })

    present_count = sum(1 for s in student_rows if s['status'] == 'present')
    late_count = sum(1 for s in student_rows if s['status'] == 'late')
    absent_count = sum(1 for s in student_rows if s['status'] == 'absent')
    excused_count = sum(1 for s in student_rows if s['status'] == 'excused')

    teacher_rows = []
    for teacher in course.teachers.all():
        cta = CourseTeacherAttendance.objects.filter(
            teacher=teacher, course=course, date=selected_date
        ).first()
        teacher_rows.append({
            'teacher': teacher,
            'status': cta.status if cta else '',
        })

    all_courses = list(Course.objects.order_by('name'))
    ids = [c.id for c in all_courses]
    idx = ids.index(course.id) if course.id in ids else None
    prev_course = all_courses[idx - 1] if idx is not None and idx > 0 else None
    next_course = all_courses[idx + 1] if idx is not None and idx < len(all_courses) - 1 else None

    context = {
        'course': course,
        'student_rows': student_rows,
        'selected_date': selected_date,
        'present_count': present_count,
        'late_count': late_count,
        'absent_count': absent_count,
        'excused_count': excused_count,
        'attendance_rate_30d': course.attendance_rate(30),
        'teacher_rows': teacher_rows,
        'all_courses': all_courses,
        'prev_course': prev_course,
        'next_course': next_course,
        'active_nav': 'courses',
    }
    return render(request, 'halaqat/course_detail.html', context)


@login_required
@require_POST
def save_course_attendance(request, course_id):
    """حفظ فوري لحالة حضور طالب أو الأستاذ ضمن دورة/درس إضافي عبر AJAX."""
    course = get_object_or_404(Course, pk=course_id)
    kind = request.POST.get('kind', 'student')
    entity_id = request.POST.get('entity_id')
    status = request.POST.get('status')
    date_str = request.POST.get('date')

    if status not in dict(Attendance.STATUS_CHOICES):
        return JsonResponse({'ok': False, 'error': 'حالة غير صالحة'}, status=400)

    try:
        selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'تاريخ غير صالح'}, status=400)

    if kind == 'teacher':
        teacher = get_object_or_404(Teacher, pk=entity_id)
        if not course.teachers.filter(pk=teacher.pk).exists():
            return JsonResponse({'ok': False, 'error': 'لا يوجد أستاذ مطابق لهذه الدورة'}, status=400)
        CourseTeacherAttendance.objects.update_or_create(
            teacher=teacher, course=course, date=selected_date,
            defaults={'status': status},
        )
    else:
        student = get_object_or_404(Student, pk=entity_id)
        if not course.students.filter(pk=student.pk).exists():
            return JsonResponse({'ok': False, 'error': 'الطالب ليس ضمن هذه الدورة'}, status=400)
        CourseAttendance.objects.update_or_create(
            student=student, course=course, date=selected_date,
            defaults={'status': status},
        )

    records = CourseAttendance.objects.filter(course=course, date=selected_date)
    counts = {
        'present': records.filter(status='present').count(),
        'late': records.filter(status='late').count(),
        'absent': records.filter(status='absent').count(),
        'excused': records.filter(status='excused').count(),
    }
    return JsonResponse({'ok': True, 'counts': counts})


@login_required
def edit_course(request, pk):
    course = get_object_or_404(Course, pk=pk)
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تحديث بيانات الدورة بنجاح.')
            _log_admin_action(request, f'✏️ تعديل دورة/درس: {course.name}')
            return redirect('admin_panel')
    else:
        form = CourseForm(instance=course)

    context = {
        'form': form,
        'course': course,
        'active_nav': 'admin',
    }
    return render(request, 'halaqat/edit_course.html', context)


@login_required
@require_POST
def delete_course(request, pk):
    course = get_object_or_404(Course, pk=pk)
    name = course.name
    course.delete()
    messages.success(request, f'تم حذف "{name}" وجميع سجلات حضورها.')
    _log_admin_action(request, f'🗑 حذف دورة/درس: {name}')
    return redirect('admin_panel')


# ============================================================
#  صفحة الأساتذة (المرتبطون بحلقة/دورة وغير المرتبطين) وتفقدهم العام
# ============================================================

@login_required
def teachers_list(request):
    """تعرض الأساتذة غير المرتبطين فقط، مع إمكانية تسجيل تفقد عام لمن لم يُؤخذ له حضور اليوم."""
    selected_date = _parse_date_param(request)
    teachers = cache_utils.free_teachers()                 # من الكاش
    general = dict(TeacherDailyAttendance.objects.filter(
        date=selected_date, teacher_id__in=[t['id'] for t in teachers],
    ).values_list('teacher_id', 'status'))                 # استعلام واحد لكل الأساتذة

    rows = []
    for teacher in teachers:
        rows.append({
            'teacher': teacher,
            'general_status': general.get(teacher['id'], ''),
            'context_notes': [],
            'has_any_record': teacher['id'] in general,
        })

    context = {
        'rows': rows,
        'selected_date': selected_date,
        'total_teachers': len(teachers),
        'unrecorded_count': sum(1 for r in rows if not r['has_any_record']),
        'active_nav': 'teachers',
    }
    return render(request, 'halaqat/teachers_list.html', context)


@login_required
@require_POST
def save_teacher_attendance_general(request):
    """حفظ فوري لتفقد عام لأستاذ عبر AJAX.

    إن كان الأستاذ مرتبطاً بحلقة أو دورة، نحفظ الحالة في سجلات الحضور المرتبطة بها
    لتُزامَن مع صفحات الحلقة/الدورة. وإلا نحفظ تفقداً عاماً فقط.
    """
    entity_id = request.POST.get('entity_id')
    status = request.POST.get('status')
    date_str = request.POST.get('date')

    if status not in dict(Attendance.STATUS_CHOICES):
        return JsonResponse({'ok': False, 'error': 'حالة غير صالحة'}, status=400)

    try:
        selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'تاريخ غير صالح'}, status=400)

    teacher = get_object_or_404(Teacher, pk=entity_id)
    linked_circles = teacher.circles.all()
    linked_courses = teacher.courses.all()

    if linked_circles.exists() or linked_courses.exists():
        for circle in linked_circles:
            TeacherAttendance.objects.update_or_create(
                teacher=teacher, circle=circle, date=selected_date,
                defaults={'status': status},
            )
        for course in linked_courses:
            CourseTeacherAttendance.objects.update_or_create(
                teacher=teacher, course=course, date=selected_date,
                defaults={'status': status},
            )
    else:
        TeacherDailyAttendance.objects.update_or_create(
            teacher=teacher, date=selected_date,
            defaults={'status': status},
        )

    return JsonResponse({'ok': True})


@login_required
@require_POST
def delete_teacher(request, pk):
    """حذف أستاذ (متاح فقط إن لم يكن مرتبطاً بأي حلقة أو دورة حالياً، لتفادي فقدان البيانات بالخطأ)."""
    teacher = get_object_or_404(Teacher, pk=pk)
    if teacher.circles.exists() or teacher.courses.exists():
        messages.error(request, f'لا يمكن حذف «{teacher.name}» لأنه مرتبط بحلقة أو دورة. عدّل الحلقة/الدورة أولاً.')
    else:
        name = teacher.name
        teacher.delete()
        messages.success(request, f'تم حذف الأستاذ «{name}».')
        _log_admin_action(request, f'🗑 حذف أستاذ: {name}')
    return redirect('teachers_list')


def _queue_whatsapp_absent_messages(selected_date, circle, message_template):
    """إرسال رسائل الغياب بشكل متسلسل في خيط منفصل مع تأخير بعد كل نجاح."""
    records = Attendance.objects.filter(date=selected_date, status='absent')
    if circle:
        records = records.filter(circle=circle)
    records = list(records.select_related('student', 'circle').order_by('circle__name', 'student__name'))

    sent_names = []
    failed_names = []
    skipped_names = []

    for index, record in enumerate(records):
        student = record.student
        phone = (student.phone or '').strip()
        if not phone:
            skipped_names.append(student.name)
            continue

        chat_id = normalize_chat_id(phone)
        if not chat_id:
            failed_names.append(student.name)
            continue

        text = message_template.format(
            student_name=student.name,
            circle_name=record.circle.name,
            date=selected_date.strftime('%Y-%m-%d'),
            week_absences=student.absence_count(7, selected_date),
            month_absences=student.absence_count(30, selected_date),
        )
        if send_whatsapp_text(chat_id, text):
            sent_names.append(student.name)
            if index != len(records) - 1:
                time.sleep(randint(1, 10))
        else:
            failed_names.append(student.name)

    summary_lines = [
        f'📤 تقرير إرسال واتساب للغياب ({selected_date.strftime("%Y-%m-%d")})',
    ]
    if circle:
        summary_lines.append(f'الحلقة: {circle.name}')
    summary_lines.append(f'✅ نجح: {", ".join(sent_names) if sent_names else "لا يوجد"}')
    summary_lines.append(f'❌ فشل/غير مُرسل: {", ".join(failed_names) if failed_names else "لا يوجد"}')
    if skipped_names:
        summary_lines.append(f'⏭ أرقام ناقصة/غير صالحة: {", ".join(skipped_names)}')

    send_telegram_message('\n'.join(summary_lines))


@login_required
def admin_panel(request):
    circle_form = CircleForm()
    student_form = StudentForm()
    course_form = CourseForm()
    whatsapp_form = WhatsAppAbsentForm()
    viewer_form = ViewerAccountForm()

    if request.method == 'POST':
        if 'submit_circle' in request.POST:
            circle_form = CircleForm(request.POST)
            if circle_form.is_valid():
                circle_form.save()
                messages.success(request, 'تمت إضافة الحلقة بنجاح.')
                return redirect('admin_panel')
        elif 'submit_student' in request.POST:
            student_form = StudentForm(request.POST)
            if student_form.is_valid():
                student_form.save()
                messages.success(request, 'تمت إضافة الطالب بنجاح.')
                return redirect('admin_panel')
        elif 'submit_course' in request.POST:
            course_form = CourseForm(request.POST)
            if course_form.is_valid():
                course_form.save()
                messages.success(request, 'تمت إضافة الدورة/الدرس بنجاح.')
                return redirect('admin_panel')
        elif 'submit_viewer' in request.POST:
            viewer_form = ViewerAccountForm(request.POST)
            if viewer_form.is_valid():
                from django.contrib.auth import get_user_model
                from django.contrib.auth.models import Group
                group, _ = Group.objects.get_or_create(name=VIEWER_GROUP)
                user = get_user_model().objects.create_user(
                    username=viewer_form.cleaned_data['username'],
                    password=viewer_form.cleaned_data['password'],
                )
                user.groups.add(group)
                messages.success(request, f'تم إنشاء حساب المشاهد «{user.username}».')
                _log_admin_action(request, f'👁 إنشاء حساب مشاهد: {user.username}')
                return redirect('admin_panel')
        elif 'submit_whatsapp_absent' in request.POST:
            whatsapp_form = WhatsAppAbsentForm(request.POST)
            if whatsapp_form.is_valid():
                selected_date = whatsapp_form.cleaned_data['date']
                circle = whatsapp_form.cleaned_data['circle']
                message_template = whatsapp_form.cleaned_data['message']

                thread = threading.Thread(
                    target=_queue_whatsapp_absent_messages,
                    args=(selected_date, circle, message_template),
                    daemon=True,
                )
                thread.start()

                messages.success(request, 'تم بدء إرسال الرسائل للغائبين بشكل متسلسل في الخلفية. سيتم إرسال ملخص النتيجة إلى التلغرام عند الانتهاء.')
                return redirect('admin_panel')

    context = {
        'circle_form': circle_form,
        'student_form': student_form,
        'course_form': course_form,
        'whatsapp_form': whatsapp_form,
        'viewer_form': viewer_form,
        'viewers': _viewer_users(),
        'circles': cache_utils.circles(),            # من الكاش (مع أعداد الطلاب)
        'students': Student.objects.select_related('circle').all(),
        'courses': Course.objects.prefetch_related('teachers', 'students').all(),
        'active_nav': 'admin',
    }
    return render(request, 'halaqat/admin_panel.html', context)


def _viewer_users():
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(groups__name=VIEWER_GROUP, is_superuser=False).order_by('username')


@login_required
@require_POST
def delete_viewer(request, pk):
    user = get_object_or_404(_viewer_users(), pk=pk)
    name = user.username
    user.delete()
    messages.success(request, f'تم حذف حساب المشاهد «{name}».')
    _log_admin_action(request, f'🗑 حذف حساب مشاهد: {name}')
    return redirect('admin_panel')


@login_required
def edit_circle(request, pk):
    circle = get_object_or_404(Circle, pk=pk)
    if request.method == 'POST':
        form = CircleForm(request.POST, instance=circle)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تحديث بيانات الحلقة بنجاح.')
            _log_admin_action(request, f'✏️ تعديل حلقة: {circle.name}')
            return redirect('admin_panel')
    else:
        form = CircleForm(instance=circle)

    context = {
        'form': form,
        'circle': circle,
        'active_nav': 'admin',
    }
    return render(request, 'halaqat/edit_circle.html', context)


@login_required
def edit_student(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == 'POST':
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تحديث بيانات الطالب بنجاح.')
            _log_admin_action(request, f'✏️ تعديل طالب: {student.name}')
            return redirect('admin_panel')
    else:
        form = StudentForm(instance=student)

    context = {
        'form': form,
        'student': student,
        'active_nav': 'admin',
    }
    return render(request, 'halaqat/edit_student.html', context)


@login_required
@require_POST
def delete_circle(request, pk):
    circle = get_object_or_404(Circle, pk=pk)
    name = circle.name
    circle.delete()  # يحذف تلقائياً طلاب الحلقة وسجلات حضورهم (CASCADE)
    messages.success(request, f'تم حذف حلقة "{name}" وجميع بياناتها المرتبطة بها.')
    _log_admin_action(request, f'🗑 حذف حلقة: {name} (وكل طلابها وسجلات حضورهم)')
    return redirect('admin_panel')


@login_required
@require_POST
def delete_student(request, pk):
    student = get_object_or_404(Student, pk=pk)
    name = student.name
    student.delete()  # يحذف تلقائياً سجلات حضوره (CASCADE)
    messages.success(request, f'تم حذف الطالب "{name}".')
    _log_admin_action(request, f'🗑 حذف طالب: {name}')
    return redirect('admin_panel')


def _parse_date_param(request, param='date'):
    date_str = request.GET.get(param)
    if date_str:
        try:
            return datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    return timezone.now().date()


def _log_admin_action(request, text):
    """يرسل سجل عملية (حذف/تعديل) من لوحة التحكم إلى بوت التلغرام، إن كان مفعّلاً."""
    if not getattr(settings, 'TELEGRAM_LOG_ADMIN_ACTIONS', False):
        return
    who = request.user.get_username() if request.user.is_authenticated else 'غير معروف'
    when = timezone.now().strftime('%Y-%m-%d %H:%M')
    send_telegram_message(f'{text}\nبواسطة: {who}\nالوقت: {when}')


@login_required
def absentees_list(request):
    """عرض الطلاب الغائبين (وقسم للطلاب المسجَّلين إذن) في تاريخ محدد، مع إمكانية تعديل الحالة مباشرة."""
    selected_date = _parse_date_param(request)
    circle_id = request.GET.get('circle')

    def build_groups(status):
        records = Attendance.objects.filter(
            date=selected_date, status=status
        ).select_related('student', 'circle').order_by('circle__name', 'student__name')
        if circle_id:
            records = records.filter(circle_id=circle_id)

        groups = {}
        for record in records:
            groups.setdefault(record.circle, []).append(record.student)

        grouped = []
        for circle, students in groups.items():
            history = _attendance_history(Attendance, {'circle': circle}, [x.id for x in students], selected_date)
            rows = []
            for student in students:
                rows.append({
                    'student': student,
                    'history': history.get(student.id),
                    'status': status,
                    'week_absences': student.absence_count(7, selected_date),
                    'month_absences': student.absence_count(30, selected_date),
                })
            grouped.append({'circle': circle, 'rows': rows})
        return grouped, records.count()

    grouped_absentees, total_absent = build_groups('absent')
    grouped_excused, total_excused = build_groups('excused')
    grouped_late, total_late = build_groups('late')

    context = {
        'selected_date': selected_date,
        'grouped_absentees': grouped_absentees,
        'grouped_excused': grouped_excused,
        'grouped_late': grouped_late,
        'total_absent': total_absent,
        'total_excused': total_excused,
        'total_late': total_late,
        'circles': Circle.objects.all(),
        'selected_circle_id': int(circle_id) if circle_id else None,
        'active_nav': 'absentees',
    }
    return render(request, 'halaqat/absentees.html', context)


@login_required
def search_students(request):
    """بحث عن طالب بالاسم، يعيد اسمه واسم حلقته (من فهرس الكاش، بلا استعلام)."""
    query = request.GET.get('q', '').strip()
    results = []
    if query:
        nq = _norm_ar(query)
        words = nq.split(' ')
        hits = []
        for sid, name, circle_id, circle_name in cache_utils.students_index()['rows']:
            n = _norm_ar(name)
            if all(w in n for w in words):
                hits.append((not n.startswith(nq), name, sid, circle_id, circle_name))
        hits.sort()
        results = [{'id': sid, 'name': name, 'circle_id': cid, 'circle_name': cname}
                   for _, name, sid, cid, cname in hits[:15]]
    return JsonResponse({'results': results})


@login_required
def students_index(request):
    """
    قائمة كل الطلاب (معرّف، اسم، حلقة) ليُخزّنها المتصفح محلياً (localStorage)
    فيتم البحث بالكامل داخل المتصفح بدل إرسال طلب للسيرفر مع كل حرف.
    ?v=<نسخة> : إن طابقت النسخة الحالية يُعاد {"same": true} فقط لتوفير البيانات.
    تُقرأ القائمة من كاش الذاكرة (لا استعلام لقاعدة البيانات)، وتُبطَل عند أي تعديل على الطلاب.
    """
    data = cache_utils.students_index()
    version = data['v']
    if request.GET.get('v') == version:
        return JsonResponse({'same': True, 'v': version})
    resp = HttpResponse(
        '{"v":"%s","students":%s}' % (version, data['payload']),
        content_type='application/json; charset=utf-8',
    )
    resp['Cache-Control'] = 'private, no-cache'
    return resp


# ============================================================
#  جرد معلومات الطالب / الأستاذ (بيانات + سجل حضور تفصيلي)
# ============================================================

def _student_month_grid(student, days=28):
    """آخر `days` يوماً (4 أسابيع) تنتهي باليوم الحالي، مع حالة حضور الطالب في كل يوم."""
    from datetime import timedelta
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    by_date = {
        r.date: r.status
        for r in Attendance.objects.filter(student=student, date__gte=start, date__lte=today)
    }
    cells = []
    counts = {'present': 0, 'late': 0, 'absent': 0, 'excused': 0, 'none': 0}
    for i in range(days):
        d = start + timedelta(days=i)
        status = by_date.get(d)
        counts[status or 'none'] += 1
        cells.append({'date': d, 'day': d.day, 'status': status, 'is_today': d == today})
    return {
        'cells': cells,
        'counts': counts,
        'total': days,
        'start': start,
        'end': today,
    }


@login_required
def student_profile(request, student_id):
    student = get_object_or_404(Student.objects.select_related('circle', 'circle__teacher'), pk=student_id)

    circle_records = Attendance.objects.filter(student=student).order_by('-date')
    course_records = CourseAttendance.objects.filter(student=student).select_related('course').order_by('-date')

    stats = {
        'present': circle_records.filter(status='present').count(),
        'late': circle_records.filter(status='late').count(),
        'excused': circle_records.filter(status='excused').count(),
        'absent': circle_records.filter(status='absent').count(),
        'total': circle_records.count(),
    }

    paginator = Paginator(circle_records, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    # الحضور الشهري: أيام الدوام = الأيام التي سُجّل فيها حضور في حلقته (أو الحلقات التي مرّ بها)
    recs = list(circle_records.values_list('circle_id', 'date', 'status'))
    circle_ids = {c for c, _, _ in recs} | {student.circle_id}
    session_days = Attendance.objects.filter(circle_id__in=circle_ids).values_list('date', flat=True).distinct()
    monthly, monthly_total = _monthly_attendance(
        [(None, d, st) for _, d, st in recs], {(None, d) for d in session_days},
        since=timezone.localtime(student.joined_at).date() if student.joined_at else None)

    context = {
        'monthly': monthly, 'monthly_total': monthly_total,
        'student': student,
        'stats': stats,
        'rate_30': student.attendance_rate(30),
        'rate_90': student.attendance_rate(90),
        'page_obj': page_obj,
        'course_records': course_records,
        'courses': student.courses.all(),
        'month': _student_month_grid(student),
        'last_sabr': student.sabrs.first(),
        'sabr': _student_sabr_stats(student),
        'recitation': _student_recitation_stats(student),
        'active_nav': None,
    }
    return render(request, 'halaqat/student_profile.html', context)


def _monthly_attendance(records, expected, since=None):
    """
    حضور كل شهر ميلادي على حدة.
    records: [(مفتاح الجلسة، التاريخ، الحالة)] — expected: {(مفتاح الجلسة، التاريخ)} أيام الدوام الفعلية.
    الأيام التي كان فيها دوام ولم يُسجَّل له فيها شيء تُحسب «لم يُسجَّل» (منذ أول سجل له).
    يعيد (صفوف الأشهر من الأحدث للأقدم، صف المجمل).
    """
    records = list(records)
    if not records:
        return [], None
    first = min(d for _, d, _ in records)
    if since and since < first:
        first = since
    slots = {(k, d) for k, d in expected if d >= first} | {(k, d) for k, d, _ in records}
    months = {}

    def row(m):
        return months.setdefault(m, {**_blank_counts(), 'expected': 0})
    for _, d in slots:
        row(d.replace(day=1))['expected'] += 1
    for _, d, st in records:
        if st in _STAT_KEYS:
            row(d.replace(day=1))[st] += 1

    def finish(c, label, key=''):
        exp = c['expected']
        rec = sum(c[k] for k in _STAT_KEYS)
        base = exp - c['excused']
        out = {'label': label, 'key': key, **c, 'total': rec, 'unrecorded': max(exp - rec, 0),
               'rate': round((c['present'] + c['late']) / base * 100) if base > 0 else None}
        for k in _STAT_KEYS:
            out['pct_' + k] = round(c[k] / exp * 100) if exp else 0
        out['pct_unrecorded'] = round(out['unrecorded'] / exp * 100) if exp else 0
        return out

    rows = [finish(c, f'{_MONTHS_AR[m.month - 1]} {m.year}', m.strftime('%Y-%m'))
            for m, c in sorted(months.items(), reverse=True)]
    tot = {'expected': 0, **_blank_counts()}
    for c in months.values():
        for k in tot:
            tot[k] += c[k]
    return rows, finish(tot, 'المجمل')


def _student_sabr_stats(student):
    """إحصائيات السبر للطالب: العدد، آخر سبر، متوسط المدة بين سبرين، والسجل مع الملاحظات."""
    items = list(student.sabrs.order_by('-date'))
    dates = sorted({x.date for x in items})
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    today = timezone.localdate()
    since = today - datetime.timedelta(days=90)
    return {
        'items': items,
        'count': len(items),
        'count_90': sum(1 for x in items if x.date >= since),
        'avg_gap': round(sum(gaps) / len(gaps)) if gaps else None,
        'days_since_last': (today - items[0].date).days if items else None,
    }


def _student_recitation_stats(student):
    """ملخص تسميع الطالب: عدد المرات، مجموع الآيات، آخر تسميع، والسجل الأخير."""
    today = timezone.localdate()
    since = today - datetime.timedelta(days=30)
    rows = list(student.recitations.values_list('from_surah', 'from_ayah', 'to_surah', 'to_ayah', 'date'))
    items = list(student.recitations.all()[:30])
    return {
        'items': items,
        'count': len(rows),
        'count_30': sum(1 for r in rows if r[4] >= since),
        'ayahs': sum(quran.safe_ayah_span(*r[:4]) for r in rows),
        'days_since_last': (today - items[0].date).days if items else None,
    }


@login_required
def student_quick_stats(request, student_id):
    """جزء HTML صغير (إحصائيات الشهر) يُحمَّل في نافذة منبثقة بدون مغادرة الصفحة."""
    student = get_object_or_404(Student.objects.select_related('circle'), pk=student_id)
    return render(request, 'halaqat/_student_month_card.html', {
        'student': student,
        'month': _student_month_grid(student),
        'quick': True,
    })


@login_required
def teacher_profile(request, teacher_id):
    teacher = get_object_or_404(Teacher, pk=teacher_id)

    circle_records = list(TeacherAttendance.objects.filter(teacher=teacher).select_related('circle'))
    course_records = list(CourseTeacherAttendance.objects.filter(teacher=teacher).select_related('course'))
    general_records = list(TeacherDailyAttendance.objects.filter(teacher=teacher))

    combined = []
    for r in circle_records:
        combined.append({'date': r.date, 'status': r.status, 'status_display': r.get_status_display(), 'source': f'حلقة {r.circle.name}'})
    for r in course_records:
        combined.append({'date': r.date, 'status': r.status, 'status_display': r.get_status_display(), 'source': f'دورة {r.course.name}'})
    for r in general_records:
        combined.append({'date': r.date, 'status': r.status, 'status_display': r.get_status_display(), 'source': 'تفقد عام'})

    combined.sort(key=lambda r: r['date'], reverse=True)

    stats = {
        'present': sum(1 for r in combined if r['status'] == 'present'),
        'late': sum(1 for r in combined if r['status'] == 'late'),
        'excused': sum(1 for r in combined if r['status'] == 'excused'),
        'absent': sum(1 for r in combined if r['status'] == 'absent'),
        'total': len(combined),
    }

    paginator = Paginator(combined, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    # الحضور الشهري من كل المصادر. أيام الدوام: أيام تسجيل طلاب حلقاته/دوراته، وأيام التفقد العام
    recs = ([(('c', r.circle_id), r.date, r.status) for r in circle_records]
            + [(('k', r.course_id), r.date, r.status) for r in course_records]
            + [(('g', 0), r.date, r.status) for r in general_records])
    expected = set()
    c_ids = {r.circle_id for r in circle_records} | set(teacher.circles.values_list('id', flat=True))
    k_ids = {r.course_id for r in course_records} | set(teacher.courses.values_list('id', flat=True))
    for cid, d in Attendance.objects.filter(circle_id__in=c_ids).values_list('circle_id', 'date').distinct():
        expected.add((('c', cid), d))
    for kid, d in CourseAttendance.objects.filter(course_id__in=k_ids).values_list('course_id', 'date').distinct():
        expected.add((('k', kid), d))
    if general_records:
        for d in TeacherDailyAttendance.objects.values_list('date', flat=True).distinct():
            expected.add((('g', 0), d))
    monthly, monthly_total = _monthly_attendance(recs, expected)

    context = {
        'monthly': monthly, 'monthly_total': monthly_total,
        'teacher': teacher,
        'stats': stats,
        'page_obj': page_obj,
        'circles': teacher.circles.all(),
        'courses': teacher.courses.all(),
        'active_nav': None,
    }
    return render(request, 'halaqat/teacher_profile.html', context)


@login_required
def export_attendance_csv(request):
    """تصدير سجل الحضور والغياب ليوم محدد (لكل الحلقات أو حلقة واحدة) كملف CSV."""
    selected_date = _parse_date_param(request)
    circle_id = request.GET.get('circle')

    circles = Circle.objects.select_related('teacher').all()
    if circle_id:
        circles = circles.filter(pk=circle_id)

    buffer = io.StringIO()
    buffer.write('\ufeff')  # BOM ليقرأ Excel النص العربي بشكل صحيح
    writer = csv.writer(buffer)
    writer.writerow(['الحلقة', 'الأستاذ', 'اسم الطالب', 'التاريخ', 'الحالة'])

    for circle in circles:
        if circle.teacher:
            ta = TeacherAttendance.objects.filter(
                teacher=circle.teacher, circle=circle, date=selected_date
            ).first()
            teacher_status_display = ta.get_status_display() if ta else 'لم يُسجَّل'
            writer.writerow([
                circle.name,
                circle.teacher.name,
                f'{circle.teacher.name} (الأستاذ)',
                selected_date.isoformat(),
                teacher_status_display,
            ])

        existing = {
            a.student_id: a.get_status_display()
            for a in Attendance.objects.filter(circle=circle, date=selected_date)
        }
        for student in circle.students.all():
            status_display = existing.get(student.id, 'لم يُسجَّل')
            writer.writerow([
                circle.name,
                circle.teacher.name if circle.teacher else '',
                student.name,
                selected_date.isoformat(),
                status_display,
            ])

    filename = f'attendance_{selected_date.isoformat()}.csv'
    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_course_attendance_csv(request):
    """تصدير سجل حضور دورة/درس إضافي ليوم محدد كملف CSV."""
    selected_date = _parse_date_param(request)
    course_id = request.GET.get('course')

    courses = Course.objects.prefetch_related('teachers', 'students').all()
    if course_id:
        courses = courses.filter(pk=course_id)

    buffer = io.StringIO()
    buffer.write('\ufeff')
    writer = csv.writer(buffer)
    writer.writerow(['الدورة/الدرس', 'الأستاذ', 'اسم الطالب', 'التاريخ', 'الحالة'])

    for course in courses:
        teacher_names = ', '.join([teacher.name for teacher in course.teachers.all()])
        for teacher in course.teachers.all():
            cta = CourseTeacherAttendance.objects.filter(
                teacher=teacher, course=course, date=selected_date
            ).first()
            teacher_status_display = cta.get_status_display() if cta else 'لم يُسجَّل'
            writer.writerow([
                course.name,
                teacher.name,
                f'{teacher.name} (الأستاذ)',
                selected_date.isoformat(),
                teacher_status_display,
            ])

        existing = {
            a.student_id: a.get_status_display()
            for a in CourseAttendance.objects.filter(course=course, date=selected_date)
        }
        for student in course.students.all():
            status_display = existing.get(student.id, 'لم يُسجَّل')
            writer.writerow([
                course.name,
                teacher_names,
                student.name,
                selected_date.isoformat(),
                status_display,
            ])

    filename = f'course_attendance_{selected_date.isoformat()}.csv'
    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ============================================================
#  إرسال نسخة احتياطية فورية كاملة إلى تلغرام (Excel)
# ============================================================

@login_required
def send_all_data_telegram(request):
    """
    يُولِّد ملف Excel متعدد الأوراق يحوي جميع بيانات المسجد
    (أساتذة، حلقات، طلاب، حضور، دورات) ويرسله فوراً إلى تلغرام.
    محمي بتسجيل الدخول ويسجّل العملية في لوحة التحكم.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        messages.error(request, '❌ مكتبة openpyxl غير مثبتة. شغّل: pip install openpyxl')
        return redirect('admin_panel')

    # ---- ثوابت التنسيق ----
    HEADER_FILL = PatternFill(start_color='B17F4A', end_color='B17F4A', fill_type='solid')
    HEADER_FONT = Font(bold=True, color='FFFFFF', name='Arial')
    HEADER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)

    def _style_sheet(ws, headers, col_widths):
        """يضيف صف العناوين بتنسيق موحّد ويضبط عرض الأعمدة."""
        ws.append(headers)
        for cell in ws[1]:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = HEADER_ALIGN
        ws.row_dimensions[1].height = 22
        for idx, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(idx)].width = width
        ws.freeze_panes = 'A2'   # تجميد صف العناوين عند التمرير
        ws.sheet_view.rightToLeft = True

    wb = openpyxl.Workbook()
    today = timezone.now().date()
    today_str = today.isoformat()

    # ── ورقة 1: الأساتذة ──────────────────────────────────────
    ws_teachers = wb.active
    ws_teachers.title = 'الأساتذة'
    # أعمدة «المعرّف» في آخر كل ورقة تجعل إعادة الاستيراد دقيقة حتى مع تكرار الأسماء
    _style_sheet(ws_teachers, ['م', 'اسم الأستاذ', 'رقم الهاتف', 'المعرّف'], [5, 30, 20, 9])
    for i, t in enumerate(Teacher.objects.order_by('name'), 1):
        ws_teachers.append([i, t.name, t.phone or '—', t.id])

    # ── ورقة 2: الحلقات ───────────────────────────────────────
    ws_circles = wb.create_sheet('الحلقات')
    _style_sheet(ws_circles,
                 ['م', 'اسم الحلقة', 'الأستاذ', 'عدد الطلاب', 'الوصف', 'ترتيب العرض', 'المعرّف', 'معرّف الأستاذ'],
                 [5, 28, 28, 12, 35, 13, 9, 11])
    for i, c in enumerate(Circle.objects.select_related('teacher').order_by('display_order', 'name'), 1):
        ws_circles.append([i, c.name,
                           c.teacher.name if c.teacher else '—',
                           c.student_count, c.description or '—', c.display_order, c.id, c.teacher_id or ''])

    # ── ورقة 3: الطلاب ────────────────────────────────────────
    ws_students = wb.create_sheet('الطلاب')
    _style_sheet(ws_students,
                 ['م', 'اسم الطالب', 'الحلقة', 'رقم الهاتف', 'ملاحظات', 'تاريخ الانضمام', 'تاريخ الميلاد', 'المعرّف', 'معرّف الحلقة'],
                 [5, 30, 28, 18, 32, 15, 15, 9, 11])
    for i, s in enumerate(
        Student.objects.select_related('circle').order_by('circle__display_order', 'circle__name', 'name'), 1
    ):
        ws_students.append([i, s.name, s.circle.name,
                            s.phone or '—', s.notes or '—',
                            s.joined_at.date().isoformat(),
                            s.birth_date.isoformat() if s.birth_date else '—',
                            s.id, s.circle_id])

    # ── ورقة 4: سجل حضور الحلقات ─────────────────────────────
    ws_att = wb.create_sheet('حضور الحلقات')
    _style_sheet(ws_att,
                 ['التاريخ', 'الحلقة', 'النوع', 'الاسم', 'الحالة', 'معرّف الشخص', 'معرّف الحلقة'],
                 [14, 28, 10, 30, 10, 11, 11])
    for ta in TeacherAttendance.objects.select_related('teacher', 'circle').order_by('-date', 'circle__name'):
        ws_att.append([ta.date.isoformat(), ta.circle.name, 'أستاذ',
                       ta.teacher.name, ta.get_status_display(), ta.teacher_id, ta.circle_id])
    for a in Attendance.objects.select_related('student', 'circle').order_by('-date', 'circle__name', 'student__name'):
        ws_att.append([a.date.isoformat(), a.circle.name, 'طالب',
                       a.student.name, a.get_status_display(), a.student_id, a.circle_id])

    # ── ورقة 5: الدورات ──────────────────────────────────────
    ws_courses = wb.create_sheet('الدورات')
    _style_sheet(ws_courses,
                 ['م', 'اسم الدورة', 'الأساتذة', 'عدد الطلاب', 'الوصف', 'المعرّف', 'معرّفات الأساتذة', 'معرّفات الطلاب'],
                 [5, 32, 32, 13, 35, 9, 14, 20])
    for i, c in enumerate(Course.objects.prefetch_related('teachers', 'students').order_by('name'), 1):
        teachers_str = '، '.join(t.name for t in c.teachers.all()) or '—'
        ws_courses.append([i, c.name, teachers_str, c.student_count, c.description or '—', c.id,
                           ','.join(str(t.id) for t in c.teachers.all()),
                           ','.join(str(x.id) for x in c.students.all())])

    # ── ورقة 6: سجل حضور الدورات ─────────────────────────────
    ws_catt = wb.create_sheet('حضور الدورات')
    _style_sheet(ws_catt,
                 ['التاريخ', 'الدورة', 'النوع', 'الاسم', 'الحالة', 'معرّف الشخص', 'معرّف الدورة'],
                 [14, 30, 10, 30, 10, 11, 11])
    for cta in CourseTeacherAttendance.objects.select_related('teacher', 'course').order_by('-date', 'course__name'):
        ws_catt.append([cta.date.isoformat(), cta.course.name, 'أستاذ',
                        cta.teacher.name, cta.get_status_display(), cta.teacher_id, cta.course_id])
    for ca in CourseAttendance.objects.select_related('student', 'course').order_by('-date', 'course__name', 'student__name'):
        ws_catt.append([ca.date.isoformat(), ca.course.name, 'طالب',
                        ca.student.name, ca.get_status_display(), ca.student_id, ca.course_id])

    # ── ورقة: التفقد العام للأساتذة ─────────────────────────
    ws_gen = wb.create_sheet('التفقد العام')
    _style_sheet(ws_gen, ['التاريخ', 'اسم الأستاذ', 'الحالة', 'معرّف الأستاذ'], [14, 30, 10, 11])
    for g in TeacherDailyAttendance.objects.select_related('teacher').order_by('-date', 'teacher__name'):
        ws_gen.append([g.date.isoformat(), g.teacher.name, g.get_status_display(), g.teacher_id])

    # ── ورقة 7: السبر ─────────────────────────────────────────
    ws_sabr = wb.create_sheet('السبر')
    _style_sheet(ws_sabr, ['التاريخ', 'اسم الطالب', 'الحلقة', 'التفاصيل والملاحظات', 'معرّف الطالب'], [14, 30, 28, 50, 11])
    for sb in Sabr.objects.select_related('student', 'student__circle').order_by('-date', 'student__name'):
        ws_sabr.append([sb.date.isoformat(), sb.student.name, sb.student.circle.name, sb.notes or '', sb.student_id])

    # ── ورقة 8: التسميع (الأعمدة M و N = أرقام السور لإعادة استيراد دقيقة) ──────────
    ws_rec = wb.create_sheet('التسميع')
    _style_sheet(ws_rec,
                 ['التاريخ', 'اسم الطالب', 'الحلقة', 'النوع', 'من سورة', 'من آية', 'إلى سورة', 'إلى آية',
                  'التقدير', 'ملاحظات', 'معرّف الطالب', 'معرّف الحلقة', 'رقم سورة البداية', 'رقم سورة النهاية'],
                 [14, 30, 28, 12, 14, 9, 14, 9, 12, 40, 11, 11, 12, 12])
    for r in Recitation.objects.select_related('student', 'circle').order_by('-date', 'student__name', 'id'):
        ws_rec.append([r.date.isoformat(), r.student.name, r.circle.name, r.get_kind_display(),
                       quran.SURAH_NAME.get(r.from_surah, ''), r.from_ayah,
                       quran.SURAH_NAME.get(r.to_surah, ''), r.to_ayah,
                       r.get_grade_display() if r.grade else '', r.notes or '',
                       r.student_id, r.circle_id, r.from_surah, r.to_surah])

    # ── تجميع الملف وإرساله ───────────────────────────────────
    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)

    # ملخص في caption التلغرام
    caption = (
        f'📊 بيانات مسجد طه — {today_str}\n'
        f'👥 الطلاب: {Student.objects.count()} | '
        f'📖 الحلقات: {Circle.objects.count()} | '
        f'🎓 الدورات: {Course.objects.count()} | '
        f'👨‍🏫 الأساتذة: {Teacher.objects.count()}'
    )
    export_filename = f'masjid_taha_{today_str}.xlsx'
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # ?download=1 → تنزيل الملف مباشرة بدل إرساله لتلغرام (يصلح لإعادة استيراده لاحقاً)
    if request.GET.get('download'):
        resp = HttpResponse(
            excel_buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{export_filename}"'
        return resp

    ok = send_telegram_document_bytes(excel_buffer.getvalue(), export_filename, caption=caption)

    if ok:
        msg = '✅ تم إرسال ملف البيانات الكاملة إلى تلغرام بنجاح.'
        _log_admin_action(request, '📤 إرسال بيانات Excel كاملة إلى تلغرام')
        if is_ajax:
            return JsonResponse({'ok': True, 'msg': msg})
        messages.success(request, msg)
    else:
        msg = '❌ فشل الإرسال إلى تلغرام. تحقق من إعدادات البوت والاتصال بالإنترنت.'
        if is_ajax:
            return JsonResponse({'ok': False, 'msg': msg})
        messages.error(request, msg)

    return redirect('admin_panel')

# ============================================================
#  ترحيل البيانات من SQLite إلى PostgreSQL
# ============================================================

# ترتيب الحذف والاستيراد يحترم علاقات FK:
#   الحذف:   TeacherDailyAttendance → CourseTeacherAttendance → CourseAttendance
#            → Course (تحذف M2M تلقائياً) → TeacherAttendance → Attendance
#            → Student → Circle → Teacher
#   الاستيراد: عكس الترتيب أعلاه تماماً

_SQLITE_TABLES = [
    # (label_ar, table_name, model_class أو None لجداول M2M)
    ('الأساتذة',            'halaqat_teacher',                    Teacher),
    ('الحلقات',             'halaqat_circle',                     Circle),
    ('الطلاب',              'halaqat_student',                    Student),
    ('حضور الطلاب',         'halaqat_attendance',                 Attendance),
    ('حضور الأساتذة',       'halaqat_teacherattendance',          TeacherAttendance),
    ('الدورات',             'halaqat_course',                     Course),
    ('أساتذة الدورات M2M',  'halaqat_course_teachers',            None),
    ('طلاب الدورات M2M',   'halaqat_course_students',            None),
    ('حضور الدورات',        'halaqat_courseattendance',           CourseAttendance),
    ('حضور أساتذة الدورات', 'halaqat_courseteacherattendance',   CourseTeacherAttendance),
    ('التفقد العام',        'halaqat_teacherdailyattendance',     TeacherDailyAttendance),
]


def _sqlite_count(conn, table):
    """إرجاع عدد الصفوف في جدول SQLite (0 إذا لم يوجد)."""
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except Exception:
        return 0


def _sqlite_read(conn, table):
    """
    يقرأ جدول SQLite بأمان ويعيد (مجموعة أسماء الأعمدة المتاحة، قائمة الصفوف).
    يعيد (set(), []) إذا لم يوجد الجدول أو كان فارغاً.
    """
    try:
        cur = conn.execute(f'PRAGMA table_info("{table}")')
        available = {row[1] for row in cur.fetchall()}
        if not available:
            return set(), []
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        return available, rows
    except Exception:
        return set(), []


def _field_default(model_cls, field_name):
    """
    يعيد القيمة الافتراضية لحقل Django — يُستخدم عند غياب العمود في SQLite القديم.
    يرجع None إذا لم يكن للحقل قيمة افتراضية.
    """
    from django.db import models as dj_models
    try:
        field = model_cls._meta.get_field(field_name)
    except Exception:
        return None
    if field.has_default():
        d = field.default
        return d() if callable(d) else d
    # احتياطي حسب نوع الحقل
    if isinstance(field, (dj_models.CharField, dj_models.TextField)):
        return ''
    if isinstance(field, (dj_models.IntegerField, dj_models.SmallIntegerField,
                          dj_models.PositiveIntegerField, dj_models.PositiveSmallIntegerField)):
        return 0
    if isinstance(field, dj_models.BooleanField):
        return False
    return None


def _col(row, col, available, fallback=None):
    """
    يقرأ قيمة عمود من صف SQLite بأمان مع حالتين:
    1. العمود غائب تماماً (أُضيف لاحقاً في PostgreSQL) → يعيد fallback.
    2. العمود موجود لكن قيمته NULL وتوجد قيمة افتراضية → يعيد fallback.
    هذا يمنع خطأ NOT NULL constraint حين تُرك الحقل فارغاً في السجلات القديمة.
    """
    if col not in available:
        return fallback
    val = row[col]
    # إذا كانت القيمة NULL في SQLite والـ fallback ليس None، استخدم الافتراضي
    if val is None and fallback is not None:
        return fallback
    return val


def _reset_pg_sequences():
    """إعادة ضبط تسلسلات auto-increment في PostgreSQL بعد INSERT بـ IDs محددة يدوياً."""
    from django.db import connection as pg_conn
    if 'postgresql' not in pg_conn.settings_dict.get('ENGINE', ''):
        return  # SQLite في بيئة الاختبار — لا حاجة لضبط تسلسلات
    seq_tables = [
        'halaqat_teacher', 'halaqat_circle', 'halaqat_student',
        'halaqat_attendance', 'halaqat_teacherattendance', 'halaqat_course',
        'halaqat_courseattendance', 'halaqat_courseteacherattendance',
        'halaqat_teacherdailyattendance',
    ]
    with pg_conn.cursor() as cur:
        for table in seq_tables:
            cur.execute(f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM "{table}"), 1)
                )
            """)


@login_required
def migrate_sqlite_to_postgres(request):
    """
    GET  → صفحة رفع ملف Excel مع إحصائيات PostgreSQL الحالية.
    POST → قراءة ملف Excel المرفوع وترحيل بياناته إلى PostgreSQL.
    ملف Excel هو نفس النسخة الاحتياطية التي تُرسَل إلى تلغرام (6 أوراق بالأسماء العربية).
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # ── بناء خريطة عكسية: قيمة display → قيمة DB (من choices الموديل) ──
    _status_map = {
        display: value
        for value, display in Attendance._meta.get_field('status').choices
    }

    def _status(arabic):
        return _status_map.get(str(arabic or '').strip(), 'present')

    def _clean(val):
        """يحوّل '—' أو None أو قيمة فارغة إلى نص فارغ."""
        s = str(val).strip() if val is not None else ''
        return '' if s in ('—', 'None', '') else s

    def _parse_date(val):
        """يعيد date من datetime أو string ISO."""
        from datetime import date as date_cls, datetime as dt_cls
        if isinstance(val, dt_cls):
            return val.date()
        if isinstance(val, date_cls):
            return val
        s = str(val).strip()[:10]
        try:
            return date_cls.fromisoformat(s)
        except ValueError:
            return None

    # ────────────────────────────────────────────────────────
    #  GET: إحصائيات PostgreSQL الحالية + نموذج رفع الملف
    # ────────────────────────────────────────────────────────
    if request.method == 'GET':
        pg_stats = [
            ('الأساتذة',              Teacher.objects.count()),
            ('الحلقات',               Circle.objects.count()),
            ('الطلاب',                Student.objects.count()),
            ('حضور الطلاب',           Attendance.objects.count()),
            ('حضور الأساتذة',         TeacherAttendance.objects.count()),
            ('السبر',                 Sabr.objects.count()),
            ('الدورات',               Course.objects.count()),
            ('حضور الدورات',          CourseAttendance.objects.count()),
            ('حضور أساتذة الدورات',   CourseTeacherAttendance.objects.count()),
        ]
        # أداة الاستيراد صارت تبويبة داخل صفحة المطور
        return redirect(reverse('developer_page') + '#import')

    # ────────────────────────────────────────────────────────
    #  POST: قراءة Excel وترحيل البيانات
    # ────────────────────────────────────────────────────────
    excel_file = request.FILES.get('excel_file')
    if not excel_file:
        err = '❌ لم يتم رفع أي ملف — اختر ملف Excel أولاً.'
        if is_ajax:
            return JsonResponse({'ok': False, 'error': err}, status=400)
        messages.error(request, err)
        return redirect(reverse('developer_page') + '#import')

    try:
        import openpyxl
        wb = openpyxl.load_workbook(excel_file, read_only=True, data_only=True)
    except Exception as exc:
        err = f'❌ تعذّر قراءة ملف Excel: {exc}'
        if is_ajax:
            return JsonResponse({'ok': False, 'error': err}, status=400)
        messages.error(request, err)
        return redirect(reverse('developer_page') + '#import')

    from .excel_import import import_workbook
    mode = 'replace' if request.POST.get('mode') == 'replace' else 'merge'
    mode_label = 'استبدال كامل' if mode == 'replace' else 'دمج'
    try:
        with transaction.atomic():
            results = import_workbook(wb, mode=mode)
    except Exception as exc:
        err = f'❌ فشل الاستيراد — تم التراجع عن كل التغييرات:\n{exc}'
        _log_admin_action(request, f'❌ فشل استيراد Excel ({mode_label}): {exc}')
        if is_ajax:
            return JsonResponse({'ok': False, 'error': str(err)}, status=400)
        messages.error(request, err)
        return redirect(reverse('developer_page') + '#import')

    cache_utils.invalidate_all()           # bulk_create لا يرسل signals → نُبطل الكاش يدوياً
    total = sum(c for _, c in results)
    _log_admin_action(request, f'📥 استيراد Excel ({mode_label}) اكتمل: أُضيف {total} سجل')

    if is_ajax:
        return JsonResponse({'ok': True, 'results': results, 'total': total})

    return render(request, 'halaqat/migrate_sqlite.html', {
        'active_nav': 'developer',
        'migration_done': True,
        'results': results,
        'total': total,
    })


# ============================================================
#  صفحة المطور
# ============================================================

@login_required
def developer_page(request):
    """صفحة المطور: تبويبات (تلغرام، تصدير Excel، استيراد Excel، معلومات قاعدة البيانات)."""
    pg_stats = _db_counts()
    return render(request, 'halaqat/developer.html', {
        'active_nav': 'developer',
        'pg_stats': pg_stats,
        'total_pg': sum(c for _, c in pg_stats),
        'cache_status': cache_utils.status(),
    })


@login_required
@require_POST
def developer_cache_refresh(request):
    """يمسح كاش الذاكرة ويعيد ملأه فوراً (مفيد بعد تعديل مباشر على قاعدة البيانات من خارج التطبيق)."""
    cache_utils.invalidate_all()
    info = cache_utils.warm_cache(close_connections=False)
    failed = info.get('failed', [])
    return JsonResponse({
        'ok': not failed, 'seconds': info.get('seconds'), 'at': info.get('at'),
        'items': info.get('ok', []), 'failed': failed,
    })


def _db_counts():
    return [
        ('الأساتذة', Teacher.objects.count()),
        ('الحلقات', Circle.objects.count()),
        ('الطلاب', Student.objects.count()),
        ('حضور الطلاب', Attendance.objects.count()),
        ('حضور الأساتذة', TeacherAttendance.objects.count()),
        ('السبر', Sabr.objects.count()),
        ('التسميع', Recitation.objects.count()),
        ('الدورات', Course.objects.count()),
        ('حضور الدورات', CourseAttendance.objects.count()),
        ('حضور أساتذة الدورات', CourseTeacherAttendance.objects.count()),
        ('التفقد العام', TeacherDailyAttendance.objects.count()),
    ]


# ============================================================
#  صفحة الإحصائيات (فلاتر: الشهر / النطاق / الفئة)
# ============================================================

_STAT_KEYS = ('present', 'late', 'absent', 'excused')
_STAT_LABELS = {'present': 'حاضر', 'late': 'تأخر', 'absent': 'غائب', 'excused': 'إذن'}


def _rate(counts):
    """نفس معادلة التطبيق: (حاضر+تأخر) / (حاضر+تأخر+غائب) — الإذن مستبعد."""
    base = counts['present'] + counts['late'] + counts['absent']
    if base == 0:
        return None
    return round((counts['present'] + counts['late']) / base * 100)


def _blank_counts():
    return {k: 0 for k in _STAT_KEYS}


def _with_pcts(c):
    """يضيف لكل حالة نسبتها المئوية من مجموع السجلات (pct_present ...) + المجموع + نسبة الحضور."""
    total = sum(c[k] for k in _STAT_KEYS)
    out = dict(c)
    out['total'] = total
    for k in _STAT_KEYS:
        out['pct_' + k] = round(c[k] / total * 100) if total else 0
    out['rate'] = _rate(c)
    return out


def _bucket_key(d, mode):
    if mode == 'day':
        return d
    if mode == 'week':                       # الأسبوع يبدأ السبت
        return d - datetime.timedelta(days=(d.weekday() + 2) % 7)
    return d.replace(day=1)


_MONTHS_AR = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
              'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']


def _bucket_label(k, mode):
    if mode == 'day':
        return f'{k.day}/{k.month}'
    if mode == 'week':
        return f'{k.day}/{k.month}'
    return f'{_MONTHS_AR[k.month - 1]} {k.year % 100:02d}'


def _stats_population_base(sources, start, end, student_meta=None):
    """
    الجزء الثقيل من إحصائيات فئة واحدة (طلاب أو كادر): يجمّع سجلات عدة مصادر ضمن الفترة [start, end]
    ويحسب نسب كل فرد (إجمالاً ثم شهراً بشهر). لا يعتمد على الفرز/البحث/الصفحة، لذا يُخزَّن في الكاش
    وتُطبَّق عليه _stats_population_view في كل طلب.
    كل مصدر: dict(qs, label, pid, pname, psub)  — label نص ثابت أو اسم حقل (يبدأ بـ '@').
    كل الأرقام تُعرض كنسب مئوية (إلى جانب العدد) لتكون قابلة للمقارنة.
    """
    from collections import defaultdict
    total = _blank_counts()
    by_source = {}
    by_date = defaultdict(_blank_counts)
    people = {}
    own_dates = defaultdict(lambda: defaultdict(set))   # pid → (رقم المصدر، المجموعة) → تواريخ سجلاته
    group_dates = {}                                    # (رقم المصدر، المجموعة) → أيام الدوام المسجّلة لرفاقه
    first_ever = {}                                     # pid → تاريخ أول سجل له
    p_month = defaultdict(lambda: defaultdict(_blank_counts))   # pid → أول يوم من الشهر → عدّادات الحالات

    for si, src in enumerate(sources):
        qs = src['qs'].filter(date__gte=start, date__lte=end)
        label_is_field = src['label'].startswith('@')
        gfield = src.get('group')
        fields = [src['pid'], src['pname'], src.get('psub') or src['pid'], 'date', 'status',
                  gfield or src['pid']]
        if label_is_field:
            fields.append(src['label'][1:])

        # أيام الدوام الفعلية لكل مجموعة (حلقة/دورة): أي يوم سُجّل فيه حضور لأي فرد منها
        eqs, efield = src.get('expected') or (src['qs'], gfield)
        eqs = eqs.filter(date__gte=start, date__lte=end)
        if efield:
            for g, d in eqs.values_list(efield, 'date').distinct():
                group_dates.setdefault((si, g), set()).add(d)
        else:
            group_dates[(si, None)] = set(eqs.values_list('date', flat=True).distinct())

        # أول سجل للشخص على الإطلاق: الأيام السابقة له لا تُحسب عليه (لم يكن منضماً بعد)
        from django.db.models import Min
        for pid, first in src['qs'].values_list(src['pid']).annotate(f=Min('date')):
            if first and (pid not in first_ever or first < first_ever[pid]):
                first_ever[pid] = first

        for row in qs.values_list(*fields):
            pid, pname, psub, d, status = row[:5]
            if status not in total:
                continue
            own_dates[pid][(si, row[5] if gfield else None)].add(d)
            if label_is_field:
                pre, val = src.get('prefix', ''), str(row[6])
                label = val if val.startswith(pre.strip()) else pre + val   # تجنّب «حلقة حلقة …»
            else:
                label = src['label']
            total[status] += 1
            by_source.setdefault(label, _blank_counts())[status] += 1
            by_date[d][status] += 1
            p = people.setdefault(pid, {'id': pid, 'name': pname, 'sub': psub if src.get('psub') else '',
                                        **_blank_counts()})
            p[status] += 1
            p_month[pid][d.replace(day=1)][status] += 1

    # صفوف المصادر (الأعلى حضوراً أولاً)
    source_rows = [{'label': label, **_with_pcts(c)} for label, c in by_source.items()]
    source_rows.sort(key=lambda r: (-(r['rate'] if r['rate'] is not None else -1), r['label']))

    # الرسم: يومي حتى شهرين، أسبوعي حتى ~8 أشهر، ثم شهري
    span = (end - start).days + 1
    mode = 'day' if span <= 62 else ('week' if span <= 250 else 'month')
    buckets = {}
    if mode == 'day':
        cur = start
        while cur <= end:                  # كل أيام الفترة حتى غير المسجّلة (تظهر فارغة)
            buckets[cur] = _blank_counts()
            cur += datetime.timedelta(days=1)
    for d, c in by_date.items():
        b = buckets.setdefault(_bucket_key(d, mode), _blank_counts())
        for k in _STAT_KEYS:
            b[k] += c[k]
    chart = []
    for k in sorted(buckets):
        c = _with_pcts(buckets[k])
        chart.append({'label': _bucket_label(k, mode), 'date': k.isoformat(),
                      **{x: c[x] for x in _STAT_KEYS}, 'total': c['total'], 'rate': c['rate'],
                      **{'pct_' + x: c['pct_' + x] for x in _STAT_KEYS}})

    # الأشخاص — النسب تُحسب من «أيام الدوام المتوقعة» (كل الأيام التي سُجّل فيها حضور
    # لرفاقه في حلقته/دورته)، لا من سجلاته هو فقط؛ فمن له سجل واحد لا تصبح نسبته 100%.
    # وتُحسب النسبة بالمعادلة نفسها لكل شهر ميلادي على حدة (أعمدة «حسب الأشهر»).
    month_keys = sorted({d.replace(day=1) for d in by_date})
    month_cols = [{'key': k.strftime('%Y-%m'), 'label': f'{_MONTHS_AR[k.month - 1]} {k.year}'}
                  for k in month_keys]
    people_rows = []
    for p in people.values():
        expected = 0
        exclusive_days = set()
        exp_m = defaultdict(int)                  # أيام الدوام المتوقعة لهذا الفرد في كل شهر
        joined = first_ever.get(p['id'], start)
        if student_meta is not None:              # تاريخ انضمام الطالب إن كان أسبق من أول سجل له
            j = student_meta.get(p['id'], {}).get('joined')
            if j and j < joined:
                joined = j
        for (si, g), mine in own_dates[p['id']].items():
            days = {d for d in group_dates.get((si, g), ()) if d >= joined} | mine
            if sources[si].get('exclusive'):
                exclusive_days |= days          # حلقة واحدة في اليوم (حتى لو انتقل الطالب بين حلقتين)
            else:
                expected += len(days)
                for d in days:
                    exp_m[d.replace(day=1)] += 1
        expected += len(exclusive_days)
        for d in exclusive_days:
            exp_m[d.replace(day=1)] += 1
        recorded = sum(p[k] for k in _STAT_KEYS)
        expected = max(expected, recorded)
        p['total'] = recorded
        p['expected'] = expected
        p['unrecorded'] = expected - recorded
        for k in _STAT_KEYS:
            p['pct_' + k] = round(p[k] / expected * 100) if expected else 0
        p['pct_unrecorded'] = round(p['unrecorded'] / expected * 100) if expected else 0
        base = expected - p['excused']          # الإذن مستبعد، وغير المسجّل يُحتسب عدم حضور
        p['rate'] = round((p['present'] + p['late']) / base * 100) if base > 0 else None

        # تفصيل كل شهر: نفس معادلة النسبة الكاملة لكن على أيام ذلك الشهر فقط (None = لا أيام له فيه)
        pm = p_month.get(p['id'], {})
        cells, mrate = [], {}
        for mk, col in zip(month_keys, month_cols):
            c = pm.get(mk)
            rec_m = sum(c[k] for k in _STAT_KEYS) if c else 0
            exp = max(exp_m.get(mk, 0), rec_m)
            if exp == 0:
                cells.append(None)
                mrate[col['key']] = None
                continue
            cc = c or _blank_counts()
            base_m = exp - cc['excused']
            rate_m = round((cc['present'] + cc['late']) / base_m * 100) if base_m > 0 else None
            cells.append({'rate': rate_m, 'recorded': rec_m, 'expected': exp, 'unrecorded': exp - rec_m,
                          'present': cc['present'], 'late': cc['late'],
                          'absent': cc['absent'], 'excused': cc['excused']})
            mrate[col['key']] = rate_m
        p['months'] = cells
        p['mrate'] = mrate

        if student_meta is not None:
            meta = student_meta.get(p['id'], {})
            p['age'] = meta.get('age')
            p['circle_order'] = meta.get('circle_order', 9999)
            p['sabr'] = meta.get('sabr', 0)
        people_rows.append(p)

    # المقارنة بالرفاق: متوسط نسبة حضور المجموعة (حلقة الطالب / كل الكادر)، الفرق عنه، والترتيب
    peers = defaultdict(list)
    for p in people_rows:
        if p['rate'] is not None:
            peers[p['sub']].append(p['rate'])
    for p in people_rows:
        rates = peers.get(p['sub'], [])
        if p['rate'] is None or not rates:
            p['peer_avg'] = p['diff'] = p['rank'] = None
            p['peer_n'] = len(rates)
            continue
        p['peer_avg'] = round(sum(rates) / len(rates))
        p['diff'] = p['rate'] - p['peer_avg']
        p['rank'] = 1 + sum(1 for r in rates if r > p['rate'])
        p['peer_n'] = len(rates)

    # «متوسط الكل»: متوسط نسب الأفراد (الإجمالية ولكل شهر) — يظهر أسفل جدول «حسب الأشهر»
    def _avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals)) if vals else None
    people_avg = {
        'rate': _avg(p['rate'] for p in people_rows),
        'months': [_avg(p['months'][i]['rate'] if p['months'][i] else None for p in people_rows)
                   for i in range(len(month_cols))],
    }

    # التفصيل الشهري: نسب كل شهر على حدة + المجمل + متوسط الأشهر
    months = {}
    for d, c in by_date.items():
        m = months.setdefault(d.replace(day=1), _blank_counts())
        for k in _STAT_KEYS:
            m[k] += c[k]
    monthly = [{'label': f'{_MONTHS_AR[k.month - 1]} {k.year}', 'key': k.strftime('%Y-%m'), **_with_pcts(v)}
               for k, v in sorted(months.items())]
    rated = [m for m in monthly if m['rate'] is not None]
    monthly_avg = None
    if monthly:
        monthly_avg = {
            'rate': round(sum(m['rate'] for m in rated) / len(rated)) if rated else None,
            **{'pct_' + k: round(sum(m['pct_' + k] for m in monthly) / len(monthly)) for k in _STAT_KEYS},
            'total': round(sum(m['total'] for m in monthly) / len(monthly)),
        }

    return {
        'monthly': monthly,
        'monthly_avg': monthly_avg,
        **_with_pcts(total),
        'counts': total,
        'sources': source_rows,
        'chart': chart,
        'chart_mode': mode,
        'session_days': len(by_date),
        'month_cols': month_cols,
        'people_avg': people_avg,
        'people_rows': people_rows,
    }


_STATS_BASE_SORTS = ('absence', 'rate', 'circle', 'age', 'name', 'diff', 'unrecorded')   # خيارات قائمة الترتيب
_STATS_COLUMN_SORTS = ('sabr', 'present', 'late', 'excused')                             # فرز بأعمدة الجدول
_MONTH_SORT_RE = re.compile(r'^m_\d{4}-\d{2}$')                                           # فرز بعمود شهر: m_2026-09


def _stats_population_view(base, sort='absence', top_limit=None, page_size=None, page=1, q='', sort_dir=None):
    """يطبّق الفرز والبحث والتقسيم لصفحات على ناتج _stats_population_base (خفيف، يُنفَّذ لكل طلب)."""
    people_rows = base['people_rows']

    # الفرز: (دالة القيمة، الاتجاه الافتراضي) — القيم الفارغة دائماً في الآخر
    sort_keys = {
        'absence': (lambda p: p['pct_absent'], 'desc'),
        'rate': (lambda p: p['rate'], 'desc'),
        'name': (lambda p: p['name'], 'asc'),
        'age': (lambda p: p.get('age'), 'asc'),
        'circle': (lambda p: (p.get('circle_order', 9999), p['sub']), 'asc'),
        'sabr': (lambda p: p.get('sabr', 0), 'desc'),
        'present': (lambda p: p['pct_present'], 'desc'),
        'late': (lambda p: p['pct_late'], 'desc'),
        'excused': (lambda p: p['pct_excused'], 'desc'),
        'unrecorded': (lambda p: p['pct_unrecorded'], 'desc'),
        'diff': (lambda p: p['diff'], 'desc'),
    }
    if _MONTH_SORT_RE.match(sort or ''):
        month_key = sort[2:]
        keyf, default_dir = (lambda p: p['mrate'].get(month_key)), 'desc'
    else:
        keyf, default_dir = sort_keys.get(sort, sort_keys['absence'])
    direction = sort_dir if sort_dir in ('asc', 'desc') else default_dir
    rows = sorted(people_rows, key=lambda p: p['name'])
    with_val = [p for p in rows if keyf(p) is not None]
    without = [p for p in rows if keyf(p) is None]
    with_val.sort(key=keyf, reverse=(direction == 'desc'))
    rows = with_val + without

    # فلترة بالاسم/الحلقة + تقسيم لصفحات (لتخفيف حجم الصفحة وسرعة التحميل)
    filtered = rows
    if q:
        nq = _norm_ar(q)
        filtered = [p for p in rows if nq in _norm_ar(p['name'] + ' ' + (p['sub'] or ''))]
    pages = 1
    if page_size:
        pages = max(1, -(-len(filtered) // page_size))
        page = min(max(1, page), pages)
        shown = filtered[(page - 1) * page_size: page * page_size]
    else:
        shown = filtered[:top_limit] if top_limit else filtered

    out = {k: v for k, v in base.items() if k != 'people_rows'}
    out.update({
        'page': page if page_size else 1,
        'pages': pages,
        'page_range': list(range(1, pages + 1)),
        'people_filtered': len(filtered),
        'sort_dir': direction,
        'people': shown,
        'people_total': len(rows),
        'people_truncated': bool(top_limit and len(rows) > top_limit),
    })
    return out


def _stats_population(sources, start, end, top_limit=None, sort='absence', student_meta=None,
                      page_size=None, page=1, q='', sort_dir=None):
    """الحساب الكامل في خطوة واحدة (بدون كاش): base ثم view."""
    base = _stats_population_base(sources, start, end, student_meta=student_meta)
    return _stats_population_view(base, sort=sort, top_limit=top_limit, page_size=page_size,
                                  page=page, q=q, sort_dir=sort_dir)


def _norm_ar(s):
    import re
    s = re.sub('[\u064B-\u0652\u0670\u0640]', '', str(s or ''))
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ى', 'ي'), ('ة', 'ه'), ('ؤ', 'و'), ('ئ', 'ي')):
        s = s.replace(a, b)
    return ' '.join(s.split()).lower()


def _parse_iso(s):
    try:
        return datetime.date.fromisoformat((s or '').strip())
    except ValueError:
        return None


def _first_record_date():
    from django.db.models import Min
    dates = [m.objects.aggregate(d=Min('date'))['d'] for m in
             (Attendance, TeacherAttendance, CourseAttendance, CourseTeacherAttendance, TeacherDailyAttendance)]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def _stats_context(request, top_limit=None, paginate=False):
    """يقرأ الفلاتر من الطلب ويحسب سياق الإحصائيات (مشترك بين الصفحة وتقرير PDF)."""
    import calendar

    today = timezone.localdate()
    g = request.GET

    # ── الفترة: من تاريخ … إلى تاريخ (مع دعم ?month=YYYY-MM القديم) ──
    start, end = _parse_iso(g.get('from')), _parse_iso(g.get('to'))
    if not start and not end and g.get('month'):
        try:
            y, m = (int(x) for x in g['month'].split('-'))
            start = datetime.date(y, m, 1)
            end = start.replace(day=calendar.monthrange(y, m)[1])
        except (ValueError, TypeError):
            pass
    first_record = cache_utils.stats_cached('first_record', _first_record_date) or today
    if not start:
        start = first_record                       # افتراضياً: من أول تاريخ مسجّل
    if not end:
        end = today                                # … إلى اليوم
    if start > end:
        start, end = end, start
    start = max(start, first_record)               # ضمن نطاق البيانات المتاحة
    end = min(end, today)
    if start > end:
        start = end

    first_this = today.replace(day=1)
    last_prev = first_this - datetime.timedelta(days=1)
    quick_ranges = [
        ('هذا الشهر', first_this, today),
        ('الشهر الماضي', last_prev.replace(day=1), last_prev),
        ('آخر 30 يوماً', today - datetime.timedelta(days=29), today),
        ('آخر 3 أشهر', today - datetime.timedelta(days=89), today),
        ('هذا العام', today.replace(month=1, day=1), today),
        ('كل الفترة', first_record, today),
    ]
    quick_ranges = [{'label': l, 'from': max(a, first_record).isoformat(), 'to': b.isoformat(),
                     'on': max(a, first_record) == start and b == end}
                    for l, a, b in quick_ranges]

    scope = g.get('scope', 'all')          # 'all' أو رقم حلقة
    who = g.get('who', 'both')             # students | staff | both
    if who not in ('students', 'staff', 'both'):
        who = 'both'
    sort = g.get('sort', 'absence')
    if not (sort in _STATS_BASE_SORTS or sort in _STATS_COLUMN_SORTS or _MONTH_SORT_RE.match(sort)):
        sort = 'absence'
    sort_dir = g.get('dir') if g.get('dir') in ('asc', 'desc') else None

    def _int(v):
        try:
            return int(v) if str(v).strip() != '' else None
        except (TypeError, ValueError):
            return None
    age_min, age_max = _int(g.get('age_min')), _int(g.get('age_max'))

    circles = list(Circle.objects.order_by('display_order', 'name'))
    circle = None
    if scope != 'all':
        try:
            circle = next((c for c in circles if c.id == int(scope)), None)
        except ValueError:
            circle = None
    scope = str(circle.id) if circle else 'all'

    # ── فلتر العمر (على الطلاب فقط) ──
    def _years_ago(n):
        try:
            return today.replace(year=today.year - n)
        except ValueError:                         # 29 فبراير
            return today.replace(year=today.year - n, day=28)
    age_q = {}
    if age_min is not None:
        age_q['student__birth_date__lte'] = _years_ago(age_min)
    if age_max is not None:
        age_q['student__birth_date__gt'] = _years_ago(age_max + 1)

    def _build_bundle():
        """الحساب الثقيل: مصادر السجلات → إحصائيات الطلاب/الكادر/السبر. يُخزَّن في الكاش لكل مجموعة فلاتر."""
        # ── مصادر البيانات حسب النطاق ──
        att_qs = Attendance.objects.filter(**age_q)
        # expected = (استعلام، حقل المجموعة) تُستخرج منه أيام الدوام الفعلية لكل حلقة/دورة
        circle_days = Attendance.objects.filter(circle=circle) if circle else Attendance.objects.all()
        student_sources = [dict(qs=att_qs, label='@circle__name', prefix='حلقة ',
                                pid='student_id', pname='student__name', psub='circle__name',
                                group='circle_id', expected=(circle_days, 'circle_id'), exclusive=True)]
        staff_sources = [dict(qs=TeacherAttendance.objects.all(), label='@circle__name', prefix='حلقة ',
                              pid='teacher_id', pname='teacher__name',
                              group='circle_id', expected=(circle_days, 'circle_id'))]
        if circle:
            student_sources[0]['qs'] = att_qs.filter(circle=circle)
            staff_sources[0]['qs'] = TeacherAttendance.objects.filter(circle=circle)
        else:
            student_sources.append(dict(qs=CourseAttendance.objects.filter(**age_q), label='@course__name', prefix='دورة ',
                                        pid='student_id', pname='student__name', psub='student__circle__name',
                                        group='course_id', expected=(CourseAttendance.objects.all(), 'course_id')))
            staff_sources.append(dict(qs=CourseTeacherAttendance.objects.all(), label='@course__name', prefix='دورة ',
                                      pid='teacher_id', pname='teacher__name',
                                      group='course_id', expected=(CourseAttendance.objects.all(), 'course_id')))
            staff_sources.append(dict(qs=TeacherDailyAttendance.objects.all(), label='التفقد العام',
                                      pid='teacher_id', pname='teacher__name',
                                      expected=(TeacherDailyAttendance.objects.all(), None)))

        student_meta = None
        if who in ('students', 'both'):
            from .models import age_from_birth_date
            order = {c.id: i for i, c in enumerate(circles)}
            from collections import Counter
            sabr_counts = Counter(Sabr.objects.filter(date__gte=start, date__lte=end).values_list('student_id', flat=True))
            student_meta = {
                sid: {'age': age_from_birth_date(bd, today) if bd else None, 'circle_order': order.get(cid, 9999),
                      'sabr': sabr_counts.get(sid, 0),
                      'joined': timezone.localtime(ja).date() if ja else None}
                for sid, bd, cid, ja in Student.objects.values_list('id', 'birth_date', 'circle_id', 'joined_at')
            }

        students_base = (_stats_population_base(student_sources, start, end, student_meta=student_meta)
                         if who in ('students', 'both') else None)
        staff_base = _stats_population_base(staff_sources, start, end) if who in ('staff', 'both') else None
        return {
            'students': students_base,
            'staff': staff_base,
            'sabr': _sabr_stats(start, end, circle, age_q, circles) if who in ('students', 'both') else None,
            'has_birth_dates': Student.objects.filter(birth_date__isnull=False).exists(),
        }

    bundle = cache_utils.stats_cached(
        f'bundle:{start}:{end}:{scope}:{who}:{age_min}:{age_max}:{today}', _build_bundle)

    try:
        page = int(g.get('page') or 1)
    except ValueError:
        page = 1
    q = (g.get('q') or '').strip()
    students_stats = (_stats_population_view(bundle['students'], sort=sort, top_limit=top_limit,
                                             page_size=25 if paginate else None, page=page, q=q, sort_dir=sort_dir)
                      if bundle['students'] is not None else None)
    staff_sort = sort if sort in ('absence', 'rate', 'name') else 'absence'
    staff_stats = (_stats_population_view(bundle['staff'], sort=staff_sort)
                   if bundle['staff'] is not None else None)

    filter_qs = request.GET.copy()
    for k in ('from', 'to', 'month', 'page'):
        filter_qs.pop(k, None)
    page_qs = request.GET.copy()
    page_qs.pop('page', None)

    # روابط فرز أعمدة الأشهر في جدول الطلاب (m_YYYY-MM)
    sort_links = _sort_links(request, sort, students_stats['sort_dir'] if students_stats else None,
                             [c['key'] for c in students_stats['month_cols']] if students_stats else ())
    if students_stats:
        students_stats['month_cols'] = [{**c, **sort_links['m_' + c['key']]} for c in students_stats['month_cols']]

    return {
        'active_nav': 'stats',
        'start': start, 'end': end, 'today': today,
        'days_span': (end - start).days + 1,
        'quick_ranges': quick_ranges, 'keep_qs': filter_qs.urlencode(),
        'circles': circles, 'scope': scope, 'circle': circle, 'who': who,
        'sort': sort, 'age_min': age_min, 'age_max': age_max,
        'sort_custom': sort not in _STATS_BASE_SORTS,       # فرز بعمود الجدول → خيار «حسب العمود المختار»
        'has_birth_dates': bundle['has_birth_dates'],
        'students_stats': students_stats, 'staff_stats': staff_stats,
        'sabr_stats': bundle['sabr'],
        'sort_links': sort_links,
        'q': q, 'page_qs': page_qs.urlencode(),
        'keep_qs_noq': '&'.join(f'{k}={v}' for k, v in page_qs.items() if k != 'q'),
        'first_record': first_record,
    }


def _sort_links(request, sort, direction, month_keys=()):
    """روابط ترويسات جدول الطلاب: الضغط يفرز، والضغط ثانيةً يعكس الاتجاه. month_keys = أعمدة الأشهر (YYYY-MM)."""
    base = request.GET.copy()
    for k in ('sort', 'dir', 'page'):
        base.pop(k, None)
    base = base.urlencode()
    out = {}
    for key in ('name', 'age', 'sabr', 'rate', 'diff', 'present', 'late', 'absence', 'excused', 'unrecorded', 'circle',
                *('m_' + mk for mk in month_keys)):
        active = key == sort
        nxt = ('asc' if direction == 'desc' else 'desc') if active else ''
        out[key] = {
            'url': f"?{base}{'&' if base else ''}sort={key}{'&dir=' + nxt if nxt else ''}#students-table",
            'arrow': (' ▼' if direction == 'desc' else ' ▲') if active else '',
        }
    return out


def _sabr_stats(start, end, circle, age_q, circles):
    """إحصائيات السبر ضمن الفترة والنطاق: العدد، نسبة الطلاب الذين سُبِروا، حسب الحلقة، وحسب الشهر."""
    from collections import Counter, defaultdict
    sq = {k.replace('student__', ''): v for k, v in age_q.items()}
    students = Student.objects.filter(**sq)
    if circle:
        students = students.filter(circle=circle)
    stu = dict(students.values_list('id', 'circle_id'))
    rows = [(sid, d) for sid, d in Sabr.objects.filter(date__gte=start, date__lte=end, student_id__in=stu.keys())
            .values_list('student_id', 'date')]
    per_student = Counter(sid for sid, _ in rows)
    by_circle_students = Counter(stu.values())
    by_circle_sabr = Counter(stu[sid] for sid, _ in rows)
    by_circle_done = Counter(stu[sid] for sid in per_student)
    circle_rows = []
    for c in circles:
        if circle and c.id != circle.id:
            continue
        n = by_circle_students.get(c.id, 0)
        if not n:
            continue
        done = by_circle_done.get(c.id, 0)
        circle_rows.append({'label': c.name, 'students': n, 'done': done,
                            'pct': round(done / n * 100), 'count': by_circle_sabr.get(c.id, 0)})
    months = defaultdict(int)
    for _, d in rows:
        months[d.replace(day=1)] += 1
    total_students = len(stu)
    return {
        'count': len(rows),
        'students': total_students,
        'done': len(per_student),
        'pct': round(len(per_student) / total_students * 100) if total_students else 0,
        'avg': round(len(rows) / total_students, 1) if total_students else 0,
        'circles': circle_rows,
        'monthly': [{'label': f'{_MONTHS_AR[k.month - 1]} {k.year}', 'count': v} for k, v in sorted(months.items())],
    }


@login_required
def stats_page(request):
    return render(request, 'halaqat/stats.html', _stats_context(request, paginate=True))


@login_required
def export_stats_pdf(request):
    """تقرير PDF بكامل الإحصائيات حسب نفس الفلاتر (الشهر / النطاق / الفئة)."""
    from .pdf_reports import build_stats_pdf
    ctx = _stats_context(request)
    pdf_bytes = build_stats_pdf(ctx)
    scope_tag = f"circle{ctx['circle'].id}" if ctx['circle'] else 'all'
    filename = f"masjid_taha_stats_{ctx['start']}_{ctx['end']}_{scope_tag}_{ctx['who']}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ============================================================
#  السبر: تسجيل آخر سبر لكل طالب
# ============================================================

def _sabr_item(sabr, today):
    return {
        'id': sabr.id,
        'date': sabr.date.isoformat(),
        'date_display': sabr.date.strftime('%Y-%m-%d'),
        'days_ago': (today - sabr.date).days,
        'notes': sabr.notes,
    }


def _sabr_payload(student):
    today = timezone.localdate()
    items = [_sabr_item(x, today) for x in student.sabrs.all()[:10]]
    return {
        'ok': True,
        'today': today.isoformat(),
        'student': {'id': student.id, 'name': student.name, 'circle': student.circle.name},
        'last': items[0] if items else None,
        'history': items,
        'total': student.sabrs.count(),
    }


def _parse_sabr_date(request):
    """يقرأ حقل date من POST (الافتراضي اليوم). يعيد (date, خطأ)."""
    raw = (request.POST.get('date') or '').strip()
    if not raw:
        return timezone.localdate(), None
    try:
        d = datetime.date.fromisoformat(raw)
    except ValueError:
        return None, 'تاريخ غير صالح'
    if d > timezone.localdate():
        return None, 'لا يمكن تسجيل سبر بتاريخ مستقبلي'
    return d, None


@login_required
def sabr_page(request):
    return render(request, 'halaqat/sabr.html', {
        'active_nav': 'sabr', 'today': timezone.localdate(),
        'read_only': False,                       # المشاهد يستطيع إضافة السبر وتعديله
        'can_delete': not is_viewer(request.user),
    })


@login_required
def sabr_student_info(request, student_id):
    student = get_object_or_404(Student.objects.select_related('circle'), pk=student_id)
    return JsonResponse(_sabr_payload(student))


@login_required
@require_POST
def sabr_add(request, student_id):
    student = get_object_or_404(Student.objects.select_related('circle'), pk=student_id)
    d, err = _parse_sabr_date(request)
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)
    notes = (request.POST.get('notes') or '').strip()
    Sabr.objects.create(student=student, date=d, notes=notes)
    return JsonResponse(_sabr_payload(student))


@login_required
@require_POST
def sabr_update(request, sabr_id):
    sabr = get_object_or_404(Sabr.objects.select_related('student', 'student__circle'), pk=sabr_id)
    d, err = _parse_sabr_date(request)
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)
    old = sabr.date
    sabr.date = d
    fields = ['date']
    if 'notes' in request.POST:
        sabr.notes = (request.POST.get('notes') or '').strip()
        fields.append('notes')
    sabr.save(update_fields=fields)
    _log_admin_action(request, f'✏️ تعديل سبر {sabr.student.name}: {old} ← {d}')
    return JsonResponse(_sabr_payload(sabr.student))


@login_required
@require_POST
def sabr_delete(request, sabr_id):
    sabr = get_object_or_404(Sabr.objects.select_related('student', 'student__circle'), pk=sabr_id)
    student = sabr.student
    _log_admin_action(request, f'🗑 حذف سبر {student.name} بتاريخ {sabr.date}')
    sabr.delete()
    return JsonResponse(_sabr_payload(student))


# ============================================================
#  فرز الطلاب بالسحب والإفلات (لوحة التحكم): كل الحلقات حاويات، والطالب بطاقة تُنقل بينها
# ============================================================

_MOVE_LOG, _MOVE_LOCK, _MOVE_TIMER = [], threading.Lock(), [None]


def _flush_student_moves():
    with _MOVE_LOCK:
        items = list(_MOVE_LOG)
        _MOVE_LOG.clear()
        _MOVE_TIMER[0] = None
    if not items:
        return
    lines = [f'🔀 نقل طلاب بين الحلقات ({len(items)}):'] + [f'• {text}' for _, text in items[:40]]
    if len(items) > 40:
        lines.append(f'… و{len(items) - 40} عملية أخرى')
    who = '، '.join(sorted({w for w, _ in items}))
    send_telegram_message('\n'.join(lines) + f'\nبواسطة: {who}\nالوقت: {timezone.localtime():%Y-%m-%d %H:%M}')


def _log_student_move(request, text):
    """يجمع عمليات النقل ويرسلها لتلغرام رسالةً واحدة بعد 20 ثانية (بلا إغراق، ودون تأخير الاستجابة)."""
    if not getattr(settings, 'TELEGRAM_LOG_ADMIN_ACTIONS', False):
        return
    who = request.user.get_username() if request.user.is_authenticated else 'غير معروف'
    with _MOVE_LOCK:
        _MOVE_LOG.append((who, text))
        if _MOVE_TIMER[0] is None:
            timer = threading.Timer(20.0, _flush_student_moves)
            timer.daemon = True
            _MOVE_TIMER[0] = timer
            timer.start()


@login_required
def sort_students_page(request):
    """لوحة فرز الطلاب: حاوية كبيرة لكل حلقة، وكل طالب بطاقة تُسحب من حلقة إلى أخرى."""
    circles = list(Circle.objects.select_related('teacher').order_by('display_order', 'name', 'id'))
    by_circle = {c.id: [] for c in circles}
    total = 0
    for sid, name, cid in Student.objects.order_by('name').values_list('id', 'name', 'circle_id'):
        by_circle.setdefault(cid, []).append({'id': sid, 'name': name})
        total += 1
    return render(request, 'halaqat/sort_students.html', {
        'boards': [{'circle': c, 'students': by_circle.get(c.id, [])} for c in circles],
        'total_students': total,
        'active_nav': 'admin',
    })


@login_required
@require_POST
def sort_students_move(request):
    """ينقل طالباً إلى حلقة أخرى (يُستدعى عند إفلات البطاقة). سجلات حضوره السابقة تبقى كما هي."""
    from django.db.models import Count
    try:
        student_id = int(request.POST.get('student_id', ''))
        circle_id = int(request.POST.get('circle_id', ''))
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'بيانات غير صالحة'}, status=400)
    student = get_object_or_404(Student.objects.select_related('circle'), pk=student_id)
    target = get_object_or_404(Circle, pk=circle_id)
    old = student.circle
    if old.id != target.id:
        student.circle = target
        student.save(update_fields=['circle', 'updated_at'])
        _log_student_move(request, f'{student.name}: «{old.name}» ← «{target.name}»')
    counts = dict(Student.objects.filter(circle_id__in=[old.id, target.id])
                  .order_by().values('circle_id').annotate(n=Count('id')).values_list('circle_id', 'n'))
    return JsonResponse({
        'ok': True,
        'student': {'id': student.id, 'name': student.name},
        'from': {'id': old.id, 'name': old.name, 'count': counts.get(old.id, 0)},
        'to': {'id': target.id, 'name': target.name, 'count': counts.get(target.id, 0)},
    })


# ============================================================
#  التسميع: تسجيل ما سمّعه الطلاب من القرآن الكريم، حلقةً حلقة
# ============================================================

def _recitation_item(r, today):
    return {
        'id': r.id,
        'date': r.date.isoformat(),
        'date_display': r.date.strftime('%Y-%m-%d'),
        'days_ago': (today - r.date).days,
        'kind': r.kind, 'kind_display': r.get_kind_display(),
        'from_surah': r.from_surah, 'from_ayah': r.from_ayah,
        'to_surah': r.to_surah, 'to_ayah': r.to_ayah,
        'range': r.range_display, 'ayahs': r.ayah_count,
        'grade': r.grade, 'grade_display': r.get_grade_display() if r.grade else '',
        'notes': r.notes,
    }


def _recitation_payload(student, on_date=None):
    """بيانات الطالب وآخر تسميعاته (+ تسميع اليوم المعروض في الصفحة إن حُدِّد on_date)."""
    today = timezone.localdate()
    qs = student.recitations.all()                      # الأحدث أولاً (ترتيب النموذج)
    items = [_recitation_item(x, today) for x in qs[:15]]
    payload = {
        'ok': True,
        'today': today.isoformat(),
        'student': {'id': student.id, 'name': student.name,
                    'circle': student.circle.name, 'circle_id': student.circle_id},
        'history': items,
        'last': items[0] if items else None,
        'total': qs.count(),
    }
    if on_date:
        payload['day'] = [_recitation_item(x, today) for x in qs.filter(date=on_date).order_by('id')]
    return payload


def _parse_recitation_post(request):
    """يقرأ حقول التسميع من POST ويتحقق منها. يعيد (قيم النموذج، نص الخطأ)."""
    post = request.POST
    raw = (post.get('date') or '').strip()
    if raw:
        d = _parse_iso(raw)
        if d is None:
            return None, 'تاريخ غير صالح'
        if d > timezone.localdate():
            return None, 'لا يمكن تسجيل تسميع بتاريخ مستقبلي'
    else:
        d = timezone.localdate()

    def _int(name):
        try:
            return int(post.get(name, ''))
        except (TypeError, ValueError):
            return None
    from_surah, from_ayah = _int('from_surah'), _int('from_ayah')
    to_surah, to_ayah = _int('to_surah'), _int('to_ayah')
    if to_surah is None:
        to_surah = from_surah
    if None in (from_surah, from_ayah, to_surah, to_ayah):
        return None, 'أكمل السورة وأرقام الآيات'
    err = quran.validate_range(from_surah, from_ayah, to_surah, to_ayah)
    if err:
        return None, err
    kind = post.get('kind') or 'new'
    if kind not in dict(Recitation.KIND_CHOICES):
        return None, 'نوع التسميع غير صالح'
    grade = post.get('grade') or ''
    if grade and grade not in dict(Recitation.GRADE_CHOICES):
        return None, 'التقدير غير صالح'
    return {
        'date': d, 'kind': kind, 'grade': grade,
        'from_surah': from_surah, 'from_ayah': from_ayah, 'to_surah': to_surah, 'to_ayah': to_ayah,
        'notes': (post.get('notes') or '').strip()[:255],
    }, None


@login_required
def recitation_page(request):
    """صفحة التسميع: اختر حلقة وتاريخاً، ثم سجّل تسميع كل طالب من الحلقة على حدة."""
    from collections import defaultdict
    from django.db.models import Max
    circles = cache_utils.circles()
    today = timezone.localdate()
    selected_date = _parse_iso(request.GET.get('date')) or today
    if selected_date > today:
        selected_date = today

    circle = prev_circle = next_circle = None
    if circles:
        wanted = request.GET.get('circle')
        circle = next((c for c in circles if str(c['id']) == str(wanted)), None) or circles[0]
        idx = [c['id'] for c in circles].index(circle['id'])
        prev_circle = circles[idx - 1] if idx > 0 else None
        next_circle = circles[idx + 1] if idx < len(circles) - 1 else None

    students = list(Student.objects.filter(circle_id=circle['id']).order_by('name')) if circle else []
    ids = [st.id for st in students]
    last_by, day_by = {}, defaultdict(list)
    if ids:
        # آخر تسميع لكل طالب: أحدث تاريخ ثم أكبر معرّف في ذلك اليوم (استعلامان صغيران بدل جلب كل السجلات)
        latest = dict(Recitation.objects.filter(student_id__in=ids).order_by()
                      .values('student_id').annotate(d=Max('date')).values_list('student_id', 'd'))
        for r in Recitation.objects.filter(student_id__in=ids, date__in=set(latest.values())).order_by('id'):
            if latest.get(r.student_id) == r.date:
                last_by[r.student_id] = r
        for r in Recitation.objects.filter(student_id__in=ids, date=selected_date).order_by('id'):
            day_by[r.student_id].append(r)

    rows = []
    for st in students:
        last = last_by.get(st.id)
        rows.append({
            'student': st,
            'last': last,
            'last_days_ago': (today - last.date).days if last else None,
            'items': day_by.get(st.id, []),
        })

    return render(request, 'halaqat/recitation.html', {
        'active_nav': 'recitation',
        'circles': circles, 'circle': circle, 'prev_circle': prev_circle, 'next_circle': next_circle,
        'rows': rows,
        'heard': sum(1 for r in rows if r['items']),
        'remaining': sum(1 for r in rows if not r['items']),
        'selected_date': selected_date, 'today': today,
        'surahs': quran.surahs_for_js(),
        'kinds': Recitation.KIND_CHOICES, 'grades': Recitation.GRADE_CHOICES,
    })


@login_required
def recitation_student_info(request, student_id):
    student = get_object_or_404(Student.objects.select_related('circle'), pk=student_id)
    return JsonResponse(_recitation_payload(student, _parse_iso(request.GET.get('date'))))


@login_required
@require_POST
def recitation_add(request, student_id):
    student = get_object_or_404(Student.objects.select_related('circle'), pk=student_id)
    data, err = _parse_recitation_post(request)
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)
    Recitation.objects.create(student=student, circle=student.circle, **data)
    return JsonResponse(_recitation_payload(student, _parse_iso(request.POST.get('ctx_date'))))


@login_required
@require_POST
def recitation_update(request, rec_id):
    rec = get_object_or_404(Recitation.objects.select_related('student', 'student__circle'), pk=rec_id)
    data, err = _parse_recitation_post(request)
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)
    for key, value in data.items():
        setattr(rec, key, value)
    rec.save()
    return JsonResponse(_recitation_payload(rec.student, _parse_iso(request.POST.get('ctx_date'))))


@login_required
@require_POST
def recitation_delete(request, rec_id):
    rec = get_object_or_404(Recitation.objects.select_related('student', 'student__circle'), pk=rec_id)
    student = rec.student
    _log_admin_action(request, f'🗑 حذف تسميع {student.name}: {rec.range_display} بتاريخ {rec.date}')
    rec.delete()
    return JsonResponse(_recitation_payload(student, _parse_iso(request.POST.get('ctx_date'))))


# ============================================================
#  المساعد الإحصائي (ذكاء اصطناعي): سؤال بالعربية ⇒ جدول + تصدير Excel / PDF
#  النموذج يحوّل السؤال إلى مواصفة منظّمة فقط؛ التنفيذ بمحرّك الإحصائيات نفسه (راجع ai_query.py).
# ============================================================

_assistant_log_ = logging.getLogger('halaqat.assistant')


def _assistant_log(request, question, spec, via, rows, ok, error=''):
    try:
        user = request.user.get_username()[:150]
        spec_json = ai_query.spec_to_json(spec) if spec else ''
        if via == 'manual' and spec_json:                # إعادة تشغيل مطابقة لآخر استعلام لا تُسجَّل مرة ثانية
            last = AssistantQuery.objects.filter(user=user).order_by('-id').values_list('spec', flat=True)[:1]
            if list(last) == [spec_json]:
                return
        AssistantQuery.objects.create(
            user=user, question=(question or '')[:500],
            spec=spec_json, via=via, rows=rows, ok=ok, error=(error or '')[:255])
    except Exception:                                   # السجل لا يجب أن يعطّل الإجابة
        _assistant_log_.exception('تعذّر حفظ سجل سؤال المساعد')


def _assistant_spec_from_post(request):
    raw = request.POST.get('spec', '')
    if not raw or len(raw) > 20000:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@login_required
def stats_assistant_page(request):
    circles = [{'id': c['id'], 'name': c['name']} for c in cache_utils.circles()]
    history = [{
        'id': h.id, 'question': h.question, 'spec': h.spec, 'via': h.via, 'ok': h.ok,
        'when': timezone.localtime(h.created_at).strftime('%Y-%m-%d %H:%M'),
    } for h in AssistantQuery.objects.filter(user=request.user.get_username()).order_by('-created_at', '-id')[:12] if h.spec]
    return render(request, 'halaqat/stats_assistant.html', {
        'active_nav': 'stats',
        'ai_enabled': bool(getattr(settings, 'ANTHROPIC_API_KEY', '')),
        'meta': ai_query.ui_meta(circles),
        'examples': ai_query.EXAMPLES,
        'history': history,
    })


def _assistant_run_response(request, raw, question, via):
    today = timezone.localdate()
    spec, warnings = ai_query.validate_spec(raw, cache_utils.circles(), today)
    try:
        result = ai_query.run_spec(spec)
    except Exception:
        _assistant_log_.exception('فشل تنفيذ استعلام المساعد: %s', spec)
        _assistant_log(request, question, spec, via, 0, False, 'خطأ أثناء التنفيذ')
        return JsonResponse({'ok': False, 'error': 'تعذّر تنفيذ الاستعلام. جرّب تبسيط السؤال أو عدّل التفسير يدوياً.'}, status=500)
    _assistant_log(request, question, spec, via, result['row_count'], True)
    return JsonResponse({'ok': True, 'spec': spec, 'result': result, 'warnings': warnings})


@login_required
@require_POST
def stats_assistant_ask(request):
    """سؤال بالذكاء الاصطناعي: السؤال ⇒ مواصفة ⇒ جدول (النموذج لا يرى أي بيانات طلاب)."""
    question = (request.POST.get('question') or '').strip()
    if not question:
        return JsonResponse({'ok': False, 'error': 'اكتب سؤالك أولاً'}, status=400)
    if len(question) > 500:
        return JsonResponse({'ok': False, 'error': 'السؤال طويل (الحد 500 حرف)'}, status=400)
    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not api_key:
        return JsonResponse({'ok': False, 'code': 'no_key',
                             'error': 'ميزة السؤال بالذكاء الاصطناعي غير مفعّلة (لم يُضبط ANTHROPIC_API_KEY). استخدم «بناء يدوي».'}, status=503)
    limit = getattr(settings, 'ASSISTANT_RATE_LIMIT_PER_HOUR', 30)
    if not cache_utils.rate_limit(f'assistant:{request.user.get_username()}', limit):
        return JsonResponse({'ok': False, 'code': 'rate',
                             'error': f'بلغتَ الحد ({limit} سؤالاً في الساعة). جرّب لاحقاً أو استخدم «بناء يدوي».'}, status=429)
    circles = cache_utils.circles()
    try:
        raw = ai_query.ask_llm(question, timezone.localdate(), [c['name'] for c in circles], api_key,
                               getattr(settings, 'ANTHROPIC_MODEL', 'claude-haiku-5-5'))
    except ai_query.AssistantError as e:
        _assistant_log(request, question, None, 'ai', 0, False, e.message)
        return JsonResponse({'ok': False, 'code': e.code, 'error': e.message}, status=502 if e.code in ('network', 'api') else 400)
    if raw.get('unsupported'):
        reason = str(raw.get('reason') or 'السؤال خارج نطاق الإحصائيات المدعومة (حضور، سبر، تسميع).')[:200]
        _assistant_log(request, question, None, 'ai', 0, False, reason)
        return JsonResponse({'ok': False, 'code': 'unsupported', 'error': reason})
    return _assistant_run_response(request, raw, question, 'ai')


@login_required
@require_POST
def stats_assistant_run(request):
    """تشغيل مواصفة (من «تعديل التفسير» أو من سجل الأسئلة) دون أي استدعاء للذكاء الاصطناعي."""
    data = _assistant_spec_from_post(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'مواصفة غير صالحة'}, status=400)
    return _assistant_run_response(request, data, '', 'manual')


@login_required
@require_POST
def stats_assistant_export(request, fmt):
    """تصدير نتيجة المواصفة نفسها إلى Excel أو PDF (تُعاد المعالجة فتتطابق مع الجدول المعروض)."""
    from django.http import Http404
    from urllib.parse import quote
    if fmt not in ('xlsx', 'pdf'):
        raise Http404
    data = _assistant_spec_from_post(request)
    if data is None:
        return HttpResponse('مواصفة غير صالحة', status=400)
    spec, _warnings = ai_query.validate_spec(data, cache_utils.circles(), timezone.localdate())
    result = ai_query.run_spec(spec)
    stamp = timezone.localtime().strftime('%Y%m%d_%H%M')
    if fmt == 'xlsx':
        content, ctype = ai_export.build_xlsx(result), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        from .pdf_reports import build_table_pdf
        content, ctype = build_table_pdf(result), 'application/pdf'
    response = HttpResponse(content, content_type=ctype)
    response['Content-Disposition'] = (f'attachment; filename="masjid_taha_stats_{stamp}.{fmt}"; '
                                       f"filename*=UTF-8''{quote(result['title'])}_{stamp}.{fmt}")
    return response
