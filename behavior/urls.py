from rest_framework.routers import DefaultRouter

from .views import BehaviorNoteViewSet


router = DefaultRouter()

router.register(
    "notes",
    BehaviorNoteViewSet,
    basename="behavior-note",
)

urlpatterns = router.urls