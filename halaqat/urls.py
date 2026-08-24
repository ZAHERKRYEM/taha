from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('circles/', views.circles_list, name='circles_list'),
    path('circles/<int:circle_id>/', views.circle_detail, name='circle_detail'),
    path('circles/<int:circle_id>/attendance/save/', views.save_attendance, name='save_attendance'),
    path('circles/<int:pk>/edit/', views.edit_circle, name='edit_circle'),
    path('circles/<int:pk>/delete/', views.delete_circle, name='delete_circle'),
    path('students/<int:pk>/edit/', views.edit_student, name='edit_student'),
    path('students/<int:pk>/delete/', views.delete_student, name='delete_student'),
    path('admin-panel/', views.admin_panel, name='admin_panel'),
    path('absentees/', views.absentees_list, name='absentees_list'),
    path('export/attendance/', views.export_attendance_csv, name='export_attendance_csv'),
    path('search-students/', views.search_students, name='search_students'),

    path('courses/', views.courses_list, name='courses_list'),
    path('courses/<int:course_id>/', views.course_detail, name='course_detail'),
    path('courses/<int:course_id>/attendance/save/', views.save_course_attendance, name='save_course_attendance'),
    path('courses/<int:pk>/edit/', views.edit_course, name='edit_course'),
    path('courses/<int:pk>/delete/', views.delete_course, name='delete_course'),
    path('export/course-attendance/', views.export_course_attendance_csv, name='export_course_attendance_csv'),

    path('teachers/', views.teachers_list, name='teachers_list'),
    path('teachers/attendance/save/', views.save_teacher_attendance_general, name='save_teacher_attendance_general'),
    path('teachers/<int:pk>/delete/', views.delete_teacher, name='delete_teacher'),

    path('students/<int:student_id>/profile/', views.student_profile, name='student_profile'),
    path('teachers/<int:teacher_id>/profile/', views.teacher_profile, name='teacher_profile'),

    # ── نسخة احتياطية فورية: يُولِّد Excel ويرسله تلغرام فوراً ──
    path('send-telegram-backup/', views.send_all_data_telegram, name='send_all_data_telegram'),

    # ── ترحيل البيانات من SQLite إلى PostgreSQL ──
    path('migrate-db/', views.migrate_sqlite_to_postgres, name='migrate_sqlite_to_postgres'),

    # ── صفحة المطور ──
    path('developer/', views.developer_page, name='developer_page'),
]
