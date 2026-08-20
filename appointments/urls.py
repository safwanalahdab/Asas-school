from rest_framework.routers import DefaultRouter

from .views import AppointmentRequestViewSet


router = DefaultRouter()

router.register(
    "",
    AppointmentRequestViewSet,
    basename="appointment-request",
)

urlpatterns = router.urls