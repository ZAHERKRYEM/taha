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
]
