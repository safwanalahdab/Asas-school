from django.contrib import admin

from .models import Notification, PushDevice


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "notification_type", "title", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("recipient__username", "title", "body", "event_key")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "platform",
        "device_name",
        "is_active",
        "masked_fcm_token",
        "last_seen_at",
        "created_at",
    )
    list_filter = ("platform", "is_active")
    search_fields = ("user__username", "installation_id", "device_name")
    readonly_fields = (
        "user",
        "installation_id",
        "fcm_token",
        "platform",
        "device_name",
        "is_active",
        "last_seen_at",
        "created_at",
        "updated_at",
    )

    @admin.display(description="FCM token")
    def masked_fcm_token(self, obj):
        token = obj.fcm_token
        return token if len(token) <= 12 else f"{token[:6]}...{token[-6:]}"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
