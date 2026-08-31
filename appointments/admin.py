from django.contrib import admin

from .models import AppointmentRequest


@admin.register(AppointmentRequest)
class AppointmentRequestAdmin(admin.ModelAdmin):
    list_display = (
        "guardian",
        "requested_date",
        "status",
        "decided_by",
        "decided_at",
        "created_at",
    )

    list_filter = (
        "status",
        "requested_date",
        "created_at",
        "decided_at",
    )

    search_fields = (
        "guardian__username",
        "guardian__first_name",
        "guardian__last_name",
        "request_reason",
        "decision_reason",
    )

    ordering = (
        "-created_at",
    )

    list_select_related = (
        "guardian",
        "decided_by",
    )

    readonly_fields = (
        "id",
        "guardian",
        "requested_date",
        "request_reason",
        "decided_by",
        "decided_at",
        "created_at",
        "updated_at",
    )

