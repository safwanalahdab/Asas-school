from rest_framework.routers import DefaultRouter

from .mobile_views import MobileSchoolRequestViewSet


router = DefaultRouter()
router.register("", MobileSchoolRequestViewSet, basename="mobile-school-request")

urlpatterns = router.urls
