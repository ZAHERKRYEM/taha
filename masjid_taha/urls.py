from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('django-admin/', admin.site.urls),  # واجهة أدمن Django الافتراضية (اختيارية للصيانة)
    path('', include('halaqat.urls')),
]
