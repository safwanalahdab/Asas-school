from rest_framework.routers import DefaultRouter

from .views import BehaviorNoteViewSet, StudentPointEntryViewSet


router = DefaultRouter()

router.register(
    "notes",
    BehaviorNoteViewSet,
    basename="behavior-note",
)
router.register(
    "points",
    StudentPointEntryViewSet,
    basename="student-point-entry",
)

urlpatterns = router.urls
