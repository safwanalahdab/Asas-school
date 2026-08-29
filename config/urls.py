"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "api/v1/auth/",
        include("accounts.auth_urls"),
    ),
    path("api/v1/accounts/", include("accounts.urls")),
    path(
        "api/schema/",
        SpectacularAPIView.as_view(),
        name="api-schema",
    ),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="api-schema"),
        name="redoc",
    ),
    path(
        "api/v1/academics/",
        include("academics.urls"),
    ),
    path(
        "api/v1/teaching/",
        include("teaching.urls"),
    ),
    path(
        "api/v1/students/",
        include("students.urls"),
    ),
    path("api/v1/attendance/", include("attendance.urls")),
    path(
        "api/v1/behavior/",
        include("behavior.urls"),
    ),
    path(
        "api/v1/homework/",
        include("homework.urls"),
    ),
    path(
        "api/v1/",
        include("announcements.urls"),
    ),
    path(
        "api/v1/requests/",
        include("school_requests.urls"),
    ),
    path(
        "api/v1/finance/",
        include("finance.urls"),
    ),
    path(
        "api/v1/appointments/",
        include("appointments.urls"),
    ),
    path(
        "api/v1/dashboard/",
        include("dashboard.urls"),
    ),
    path(
        "api/v1/grades/",
        include("grades.urls"),
    ),
    path("api/v1/", include("audit_logs.urls")),
    path(
        "api/v1/mobile/",
        include("students.mobile_urls"),
    ),
]
