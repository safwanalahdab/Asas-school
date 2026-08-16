from django.utils import timezone
from rest_framework import serializers

from .models import BehaviorNote


class BehaviorNoteSerializer(serializers.ModelSerializer):
    note_type_display = serializers.CharField(
        source="get_note_type_display",
        read_only=True,
    )

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = BehaviorNote

        fields = (
            "id",
            "enrollment",
            "note_type",
            "note_type_display",
            "title",
            "description",
            "occurred_on",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_by",
            "created_at",
            "updated_at",
        )

