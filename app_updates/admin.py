from django.contrib import admin

from .models import AppUpdatePolicy


@admin.register(AppUpdatePolicy)
class AppUpdatePolicyAdmin(admin.ModelAdmin):
    # نموذج ModelAdmin الافتراضي (ModelForm) يستدعي full_clean() قبل الحفظ،
    # فتطبَّق قواعد clean() والـConstraints على كل إضافة وتعديل.
    list_display = (
        "platform",
        "is_check_enabled",
        "latest_version",
        "latest_build",
        "minimum_supported_build",
        "updated_at",
    )
    list_filter = ("platform", "is_check_enabled")
    readonly_fields = ("id", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        if obj is not None:
            # المنصة تُختار عند الإنشاء فقط.
            return (*readonly, "platform")
        return readonly

    def has_delete_permission(self, request, obj=None):
        return False
