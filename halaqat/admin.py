from django.contrib import admin
from .models import (
    Teacher, Circle, Student, Attendance, TeacherAttendance,
    Course, CourseAttendance, CourseTeacherAttendance, TeacherDailyAttendance, Sabr, Recitation, AssistantQuery,
)


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
    list_display = ('name', 'phone', 'circle')
    search_fields = ('name', 'phone')
    list_filter = ('circle',)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'circle', 'date', 'status')
    list_filter = ('circle', 'status', 'date')
    date_hierarchy = 'date'


@admin.register(TeacherAttendance)
class TeacherAttendanceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'circle', 'date', 'status')
    list_filter = ('circle', 'status', 'date')
    date_hierarchy = 'date'

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_teachers', 'student_count')
    search_fields = ('name',)
    filter_horizontal = ('teachers', 'students')

    def get_teachers(self, obj):
        return ', '.join([teacher.name for teacher in obj.teachers.all()])
    get_teachers.short_description = 'الأساتذة'


@admin.register(CourseAttendance)
class CourseAttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'date', 'status')
    list_filter = ('course', 'status', 'date')
    date_hierarchy = 'date'


@admin.register(CourseTeacherAttendance)
class CourseTeacherAttendanceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'course', 'date', 'status')
    list_filter = ('course', 'status', 'date')
    date_hierarchy = 'date'


@admin.register(TeacherDailyAttendance)
class TeacherDailyAttendanceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'date', 'status')
    list_filter = ('status', 'date')
    date_hierarchy = 'date'


@admin.register(Sabr)
class SabrAdmin(admin.ModelAdmin):
    list_display = ('student', 'date')
    list_filter = ('date',)
    search_fields = ('student__name',)


@admin.register(Recitation)
class RecitationAdmin(admin.ModelAdmin):
    list_display = ('student', 'circle', 'date', 'kind', 'grade')
    list_filter = ('circle', 'kind', 'grade', 'date')
    search_fields = ('student__name',)
    date_hierarchy = 'date'


@admin.register(AssistantQuery)
class AssistantQueryAdmin(admin.ModelAdmin):
    list_display = ('user', 'question', 'via', 'rows', 'ok', 'created_at')
    list_filter = ('via', 'ok', 'user')
    search_fields = ('question', 'user')
    readonly_fields = ('created_at',)
