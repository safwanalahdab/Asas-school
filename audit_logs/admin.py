from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_display", "module", "action", "target_display")
    list_filter = ("module", "action", "created_at")
    search_fields = ("actor_display", "message", "target_display", "target_id")
    readonly_fields = tuple(field.name for field in AuditLog._meta.fields)
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
