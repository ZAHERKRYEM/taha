import datetime

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Teacher, Circle, Student, Attendance
from .forms import CircleForm, StudentForm


@login_required
def circles_list(request):
    circles = Circle.objects.select_related('teacher').all()
    today = timezone.now().date()

    circle_cards = []
    for circle in circles:
        total_students = circle.student_count
        today_records = Attendance.objects.filter(circle=circle, date=today)
        present_today = today_records.filter(status='present').count()
        rate = None
        if today_records.exists():
            counted = today_records.exclude(status='excused').count()
            rate = round((present_today / counted) * 100) if counted else None
        circle_cards.append({
            'circle': circle,
            'student_count': total_students,
            'today_rate': rate,
        })

    context = {
        'circle_cards': circle_cards,
        'total_circles': circles.count(),
        'total_students': Student.objects.count(),
        'today': today,
        'active_nav': 'circles',
    }
    return render(request, 'halaqat/circles_list.html', context)


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

    student_rows = []
    for student in students:
        student_rows.append({
            'student': student,
            'status': existing.get(student.id, ''),  # فارغ = لم يُسجَّل بعد
        })

    present_count = sum(1 for s in student_rows if s['status'] == 'present')
    absent_count = sum(1 for s in student_rows if s['status'] == 'absent')
    excused_count = sum(1 for s in student_rows if s['status'] == 'excused')

    context = {
        'circle': circle,
        'student_rows': student_rows,
        'selected_date': selected_date,
        'present_count': present_count,
        'absent_count': absent_count,
        'excused_count': excused_count,
        'attendance_rate_30d': circle.attendance_rate(30),
        'active_nav': 'circles',
    }
    return render(request, 'halaqat/circle_detail.html', context)


@login_required
@require_POST
def save_attendance(request, circle_id):
    """حفظ فوري لحالة حضور طالب واحد عبر AJAX - بدون زر حفظ."""
    circle = get_object_or_404(Circle, pk=circle_id)
    student_id = request.POST.get('student_id')
    status = request.POST.get('status')
    date_str = request.POST.get('date')

    if status not in dict(Attendance.STATUS_CHOICES):
        return JsonResponse({'ok': False, 'error': 'حالة غير صالحة'}, status=400)

    try:
        selected_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'تاريخ غير صالح'}, status=400)

    student = get_object_or_404(Student, pk=student_id, circle=circle)

    Attendance.objects.update_or_create(
        student=student, date=selected_date,
        defaults={'circle': circle, 'status': status},
    )

    records = Attendance.objects.filter(circle=circle, date=selected_date)
    counts = {
        'present': records.filter(status='present').count(),
        'absent': records.filter(status='absent').count(),
        'excused': records.filter(status='excused').count(),
    }
    return JsonResponse({'ok': True, 'counts': counts})


@login_required
def admin_panel(request):
    circle_form = CircleForm()
    student_form = StudentForm()

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

    context = {
        'circle_form': circle_form,
        'student_form': student_form,
        'circles': Circle.objects.select_related('teacher').all(),
        'students': Student.objects.select_related('circle').all(),
        'active_nav': 'admin',
    }
    return render(request, 'halaqat/admin_panel.html', context)


@login_required
def edit_circle(request, pk):
    circle = get_object_or_404(Circle, pk=pk)
    if request.method == 'POST':
        form = CircleForm(request.POST, instance=circle)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تحديث بيانات الحلقة بنجاح.')
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
            return redirect('admin_panel')
    else:
        form = StudentForm(instance=student)

    context = {
        'form': form,
        'student': student,
        'active_nav': 'admin',
    }
    return render(request, 'halaqat/edit_student.html', context)
