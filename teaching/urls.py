from rest_framework.routers import DefaultRouter

from .views import TeacherAssignmentViewSet


router = DefaultRouter()

router.register(
    "assignments",
    TeacherAssignmentViewSet,
    basename="teacher-assignment",
)

urlpatterns = router.urls