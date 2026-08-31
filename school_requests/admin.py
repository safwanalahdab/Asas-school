from django.contrib import admin

from .models import SchoolRequest


@admin.register(SchoolRequest)
class SchoolRequestAdmin(admin.ModelAdmin):
    list_display = (
        "request_type",
        "guardian",
        "student",
        "status",
        "handled_by",
        "created_at",
        "answered_at",
    )

    list_filter = (
        "request_type",
        "status",
        "created_at",
        "answered_at",
    )

    search_fields = (
        "details",
        "school_response",
        "guardian__username",
        "guardian__first_name",
        "guardian__last_name",
        "student__first_name",
        "student__last_name",
    )

    ordering = (
        "-created_at",
    )

    list_select_related = (
        "guardian",
        "student",
        "handled_by",
    )

    readonly_fields = (
        "id",
        "request_type",
        "details",
        "guardian",
        "student",
        "status",
        "handled_by",
        "answered_at",
        "created_at",
        "updated_at",
    )

