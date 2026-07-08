from django.contrib import admin
from .models import Teacher, Circle, Student, Attendance


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone')
    search_fields = ('name',)


@admin.register(Circle)
class CircleAdmin(admin.ModelAdmin):
    list_display = ('name', 'teacher', 'student_count')
    search_fields = ('name',)
    list_filter = ('teacher',)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('name', 'circle')
    search_fields = ('name',)
    list_filter = ('circle',)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'circle', 'date', 'status')
    list_filter = ('circle', 'status', 'date')
    date_hierarchy = 'date'
