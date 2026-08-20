from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    GradeTuitionPlanViewSet,
    StudentFinancialAccountViewSet,
)


router = DefaultRouter()

router.register(
    "tuition-plans",
    GradeTuitionPlanViewSet,
    basename="tuition-plan",
)

router.register(
    "accounts",
    StudentFinancialAccountViewSet,
    basename="financial-account",
)


urlpatterns = [
    path("", include(router.urls)),
]