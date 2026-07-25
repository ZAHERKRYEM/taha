from django.db import models
from django.utils import timezone


class Teacher(models.Model):
    """المعلم المسؤول عن حلقة أو أكثر"""
    name = models.CharField('اسم الأستاذ', max_length=150)
    phone = models.CharField('رقم الهاتف', max_length=20, blank=True)

    class Meta:
        verbose_name = 'أستاذ'
        verbose_name_plural = 'الأساتذة'
        ordering = ['name']

    def __str__(self):
        return self.name


class Circle(models.Model):
    """حلقة قرآنية"""
    name = models.CharField('اسم الحلقة', max_length=150)
    teacher = models.ForeignKey(
        Teacher, verbose_name='الأستاذ المسؤول',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='circles',
    )
    description = models.CharField('وصف مختصر', max_length=255, blank=True)
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)

    class Meta:
        verbose_name = 'حلقة'
        verbose_name_plural = 'الحلقات'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def student_count(self):
        return self.students.count()

    def attendance_rate(self, days=30):
        """نسبة الحضور خلال آخر عدد أيام محدد (احتساب: حاضر / (حاضر+غائب))"""
        since = timezone.now().date() - timezone.timedelta(days=days)
        qs = Attendance.objects.filter(circle=self, date__gte=since)
        total = qs.exclude(status='excused').count()
        if total == 0:
            return None
        present = qs.filter(status='present').count()
        return round((present / total) * 100)

    def attendance_progress(self, date):
        """هل تم تسجيل حضور الجميع (كل الطلاب + الأستاذ) في هذا التاريخ؟ يُستخدم لتلوين كرت الحلقة."""
        total = self.student_count
        recorded = Attendance.objects.filter(circle=self, date=date).count()
        if self.teacher:
            total += 1
            if TeacherAttendance.objects.filter(teacher=self.teacher, circle=self, date=date).exists():
                recorded += 1
        return {'total': total, 'recorded': recorded, 'complete': total > 0 and recorded >= total}


class Student(models.Model):
    """طالب داخل حلقة"""
    name = models.CharField('اسم الطالب', max_length=150)
    circle = models.ForeignKey(
        Circle, verbose_name='الحلقة',
        on_delete=models.CASCADE, related_name='students',
    )
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    joined_at = models.DateTimeField('تاريخ الانضمام', auto_now_add=True)

    class Meta:
        verbose_name = 'طالب'
        verbose_name_plural = 'الطلاب'
        ordering = ['name']

    def __str__(self):
        return self.name

    def attendance_rate(self, days=90):
        since = timezone.now().date() - timezone.timedelta(days=days)
        qs = Attendance.objects.filter(student=self, date__gte=since)
        total = qs.exclude(status='excused').count()
        if total == 0:
            return None
        present = qs.filter(status='present').count()
        return round((present / total) * 100)

    def absence_count(self, days, before_date=None):
        """عدد أيام الغياب خلال آخر (days) يوماً، محسوبة قبل تاريخ محدد (افتراضياً اليوم)."""
        before_date = before_date or timezone.now().date()
        since = before_date - timezone.timedelta(days=days - 1)
        return Attendance.objects.filter(
            student=self, status='absent', date__gte=since, date__lte=before_date,
        ).count()


class Attendance(models.Model):
    """سجل حضور يومي لطالب في حلقة - سجل تاريخي بالتاريخ"""

    STATUS_CHOICES = [
        ('present', 'حاضر'),
        ('absent', 'غائب'),
        ('excused', 'إذن'),
    ]

    student = models.ForeignKey(
        Student, verbose_name='الطالب',
        on_delete=models.CASCADE, related_name='attendance_records',
    )
    circle = models.ForeignKey(
        Circle, verbose_name='الحلقة',
        on_delete=models.CASCADE, related_name='attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'سجل حضور'
        verbose_name_plural = 'سجلات الحضور'
        # طالب واحد لا يمكن أن يملك أكثر من سجل حضور في نفس اليوم
        unique_together = [('student', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.student.name} - {self.date} - {self.get_status_display()}'


class TeacherAttendance(models.Model):
    """سجل حضور يومي للأستاذ المسؤول عن حلقة - بنفس منطق حضور الطلاب"""

    STATUS_CHOICES = Attendance.STATUS_CHOICES

    teacher = models.ForeignKey(
        Teacher, verbose_name='الأستاذ',
        on_delete=models.CASCADE, related_name='attendance_records',
    )
    circle = models.ForeignKey(
        Circle, verbose_name='الحلقة',
        on_delete=models.CASCADE, related_name='teacher_attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'حضور أستاذ'
        verbose_name_plural = 'حضور الأساتذة'
        # الأستاذ لا يمكن أن يملك أكثر من سجل حضور لنفس الحلقة في نفس اليوم
        unique_together = [('teacher', 'circle', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.teacher.name} - {self.circle.name} - {self.date} - {self.get_status_display()}'


class Course(models.Model):
    """دورة أو درس إضافي لفئة محددة من الطلاب (مستقل عن الحلقات الأساسية)"""
    name = models.CharField('اسم الدورة / الدرس', max_length=150)
    teacher = models.ForeignKey(
        Teacher, verbose_name='الأستاذ / المحاضر المسؤول',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='courses',
    )
    description = models.CharField('وصف مختصر', max_length=255, blank=True)
    students = models.ManyToManyField(
        Student, verbose_name='الطلاب المشاركون',
        related_name='courses', blank=True,
    )
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)

    class Meta:
        verbose_name = 'دورة / درس إضافي'
        verbose_name_plural = 'الدورات والدروس الإضافية'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def student_count(self):
        return self.students.count()

    def attendance_rate(self, days=30):
        since = timezone.now().date() - timezone.timedelta(days=days)
        qs = CourseAttendance.objects.filter(course=self, date__gte=since)
        total = qs.exclude(status='excused').count()
        if total == 0:
            return None
        present = qs.filter(status='present').count()
        return round((present / total) * 100)

    def attendance_progress(self, date):
        """هل تم تسجيل حضور جميع المشاركين (+الأستاذ إن وُجد) في هذا التاريخ؟"""
        total = self.student_count
        recorded = CourseAttendance.objects.filter(course=self, date=date).count()
        if self.teacher:
            total += 1
            if CourseTeacherAttendance.objects.filter(teacher=self.teacher, course=self, date=date).exists():
                recorded += 1
        return {'total': total, 'recorded': recorded, 'complete': total > 0 and recorded >= total}


class CourseAttendance(models.Model):
    """سجل حضور يومي لطالب مشارك في دورة/درس إضافي - مستقل عن حضور الحلقة الأساسية"""

    STATUS_CHOICES = Attendance.STATUS_CHOICES

    student = models.ForeignKey(
        Student, verbose_name='الطالب',
        on_delete=models.CASCADE, related_name='course_attendance_records',
    )
    course = models.ForeignKey(
        Course, verbose_name='الدورة / الدرس',
        on_delete=models.CASCADE, related_name='attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'حضور دورة'
        verbose_name_plural = 'سجلات حضور الدورات'
        unique_together = [('student', 'course', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.student.name} - {self.course.name} - {self.date} - {self.get_status_display()}'


class CourseTeacherAttendance(models.Model):
    """سجل حضور يومي لأستاذ/محاضر دورة أو درس إضافي"""

    STATUS_CHOICES = Attendance.STATUS_CHOICES

    teacher = models.ForeignKey(
        Teacher, verbose_name='الأستاذ',
        on_delete=models.CASCADE, related_name='course_attendance_records',
    )
    course = models.ForeignKey(
        Course, verbose_name='الدورة / الدرس',
        on_delete=models.CASCADE, related_name='teacher_attendance_records',
    )
    date = models.DateField('التاريخ', default=timezone.now)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='present')
    recorded_at = models.DateTimeField('وقت التسجيل', auto_now=True)

    class Meta:
        verbose_name = 'حضور أستاذ دورة'
        verbose_name_plural = 'حضور أساتذة الدورات'
        unique_together = [('teacher', 'course', 'date')]
        ordering = ['-date']

    def __str__(self):
        return f'{self.teacher.name} - {self.course.name} - {self.date} - {self.get_status_display()}'