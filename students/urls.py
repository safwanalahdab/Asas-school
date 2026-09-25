from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EnrollmentViewSet,
    GuardianStudentViewSet,
    StudentHealthProfileView,
    StudentRegistrationView,
    StudentViewSet,
)
from .profile_views import StudentProfileView
from .student_import_api import StudentImportUploadView


router = DefaultRouter()

router.register(
    "students",
    StudentViewSet,
    basename="student",
)

router.register(
    "guardian-links",
    GuardianStudentViewSet,
    basename="guardian-student",
)

router.register(
    "enrollments",
    EnrollmentViewSet,
    basename="enrollment",
)


urlpatterns = [
    path("imports/", StudentImportUploadView.as_view(), name="student-import-upload"),
    path("register/", StudentRegistrationView.as_view(), name="student-register"),
    path(
        "<uuid:student_id>/profile/",
        StudentProfileView.as_view(),
        name="student-profile",
    ),
    path(
        "<uuid:student_id>/health-profile/",
        StudentHealthProfileView.as_view(),
        name="student-health-profile",
    ),
    path("", include(router.urls)),
]
