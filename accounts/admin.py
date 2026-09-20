from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm
from django.core.exceptions import ValidationError

from .models import User


class CustomUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if role == User.Role.SUPERVISOR:
            raise ValidationError(
                "يتم إنشاء الموجّه عبر Accounts API لأن نطاق المراحل "
                "(SupervisorScope) إلزامي."
            )
        return role


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            readonly.append("role")
        return tuple(readonly)

    fieldsets = UserAdmin.fieldsets + (
        (
            "بيانات منصة أساس",
            {
                "fields": (
                    "national_id",
                    "phone_number",
                    "role",
                    "must_change_password",
                )
            },
        ),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "بيانات منصة أساس",
            {
                "fields": (
                    "email",
                    "national_id",
                    "phone_number",
                    "role",
                    "must_change_password",
                )
            },
        ),
    )

    list_display = (
        "username",
        "national_id",
        "phone_number",
        "email",
        "role",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "role",
        "is_active",
        "is_staff",
    )

    search_fields = (
        "username",
        "national_id",
        "phone_number",
        "first_name",
        "last_name",
        "email",
    )
