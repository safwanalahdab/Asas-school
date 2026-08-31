from rest_framework.routers import DefaultRouter

from .mobile_views import MobileAppointmentRequestViewSet


router = DefaultRouter()
router.register("", MobileAppointmentRequestViewSet, basename="mobile-appointment")

urlpatterns = router.urls
