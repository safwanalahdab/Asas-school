from rest_framework.routers import DefaultRouter

from .views import SchoolRequestViewSet


router = DefaultRouter()

router.register(
    "",
    SchoolRequestViewSet,
    basename="school-request",
)

urlpatterns = router.urls