from django.db import transaction

from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from accounts.permissions import IsWebDashboardUser

from .models import BehaviorNote
from .permissions import CanAccessBehaviorNotes
from .serializers import BehaviorNoteSerializer
from .services import notify_behavior_note_created
from config.api_responses import ArabicApiResponseMixin


class BehaviorNoteViewSet(
    ArabicApiResponseMixin,
    ModelViewSet,
):
    queryset = BehaviorNote.objects.select_related(
        "enrollment",
        "created_by",
    )

    serializer_class = BehaviorNoteSerializer

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        CanAccessBehaviorNotes,
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
        "delete",
    ]
    response_messages = {
        "list": (
            "BEHAVIOR_NOTES_RETRIEVED",
            "تم جلب الملاحظات السلوكية بنجاح.",
        ),
        "retrieve": (
            "BEHAVIOR_NOTE_RETRIEVED",
            "تم جلب الملاحظة السلوكية بنجاح.",
        ),
        "create": (
            "BEHAVIOR_NOTE_CREATED",
            "تمت إضافة الملاحظة السلوكية بنجاح.",
        ),
        "partial_update": (
            "BEHAVIOR_NOTE_UPDATED",
            "تم تحديث الملاحظة السلوكية بنجاح.",
        ),
        "destroy": (
            "BEHAVIOR_NOTE_DELETED",
            "تم حذف الملاحظة السلوكية بنجاح.",
        ),
    }

    @transaction.atomic
    def perform_create(self, serializer):
        behavior_note = serializer.save(
            created_by=self.request.user,
        )
        notify_behavior_note_created(behavior_note)
from django.db import transaction
