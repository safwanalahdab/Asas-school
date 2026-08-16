from django.contrib import admin

from .models import BehaviorNote


@admin.register(BehaviorNote)
class BehaviorNoteAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "note_type",
        "enrollment",
        "occurred_on",
        "created_by",
        "created_at",
    )

    list_filter = (
        "note_type",
        "occurred_on",
        "created_at",
    )

    search_fields = (
        "title",
        "description",
        "enrollment__student__first_name",
        "enrollment__student__last_name",
    )

    ordering = (
        "-occurred_on",
        "-created_at",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )