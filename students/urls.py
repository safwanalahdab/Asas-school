from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EnrollmentViewSet,
    GuardianStudentViewSet,
    StudentViewSet,
)


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
    path("", include(router.urls)),
]