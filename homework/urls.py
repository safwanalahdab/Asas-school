from rest_framework.routers import DefaultRouter

from .views import HomeworkViewSet


router = DefaultRouter()

router.register(
    "homeworks",
    HomeworkViewSet,
    basename="homework",
)

urlpatterns = router.urls