from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "بيانات منصة أساس",
            {
                "fields": (
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
                    "role",
                    "must_change_password",
                )
            },
        ),
    )

    list_display = (
        "username",
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
        "first_name",
        "last_name",
        "email",
    )