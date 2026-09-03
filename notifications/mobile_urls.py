from rest_framework.routers import DefaultRouter

from .mobile_views import MobileNotificationViewSet


router = DefaultRouter()
router.register("", MobileNotificationViewSet, basename="mobile-notification")

urlpatterns = router.urls
