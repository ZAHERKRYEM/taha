from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('home/', views.home, name='home'),
    path('help/', views.help_page, name='help_page'),
    path('circles/', views.circles_list, name='circles_list'),
    path('circles/<int:circle_id>/', views.circle_detail, name='circle_detail'),
    path('circles/<int:circle_id>/attendance/save/', views.save_attendance, name='save_attendance'),
    path('circles/<int:pk>/edit/', views.edit_circle, name='edit_circle'),
    path('circles/<int:pk>/delete/', views.delete_circle, name='delete_circle'),
    path('students/<int:pk>/edit/', views.edit_student, name='edit_student'),
    path('students/<int:pk>/delete/', views.delete_student, name='delete_student'),
    path('admin-panel/', views.admin_panel, name='admin_panel'),
    path('admin-panel/viewers/<int:pk>/delete/', views.delete_viewer, name='delete_viewer'),
    path('absentees/', views.absentees_list, name='absentees_list'),
    path('export/attendance/', views.export_attendance_csv, name='export_attendance_csv'),
    path('search-students/', views.search_students, name='search_students'),
    path('students/index.json', views.students_index, name='students_index'),

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

    # ── إحصائيات الطالب السريعة (آخر 4 أسابيع) ──
    path('students/<int:student_id>/quick-stats/', views.student_quick_stats, name='student_quick_stats'),

    # ── السبر ──
    path('sabr/', views.sabr_page, name='sabr_page'),
    path('sabr/student/<int:student_id>/', views.sabr_student_info, name='sabr_student_info'),
    path('sabr/student/<int:student_id>/add/', views.sabr_add, name='sabr_add'),
    path('sabr/<int:sabr_id>/update/', views.sabr_update, name='sabr_update'),
    path('sabr/<int:sabr_id>/delete/', views.sabr_delete, name='sabr_delete'),

    # ── الإحصائيات ──
    path('stats/', views.stats_page, name='stats_page'),
    path('stats/pdf/', views.export_stats_pdf, name='export_stats_pdf'),

    # ── صفحة المطور ──
    path('developer/', views.developer_page, name='developer_page'),
]
