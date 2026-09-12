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
