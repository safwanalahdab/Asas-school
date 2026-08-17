from django import forms
from django.contrib import admin

from .models import Announcement


class AnnouncementAdminForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        scope = cleaned_data.get("scope")
        grade_levels = cleaned_data.get("grade_levels")
        sections = cleaned_data.get("sections")

        has_grades = bool(grade_levels)
        has_sections = bool(sections)

        if scope == Announcement.Scope.ALL:
            if has_grades:
                self.add_error(
                    "grade_levels",
                    "لا يمكن تحديد صفوف عندما يكون الإعلان لجميع المدرسة.",
                )

            if has_sections:
                self.add_error(
                    "sections",
                    "لا يمكن تحديد شعب عندما يكون الإعلان لجميع المدرسة.",
                )

        elif scope == Announcement.Scope.GRADES:
            if not has_grades:
                self.add_error(
                    "grade_levels",
                    "يجب تحديد صف واحد على الأقل.",
                )

            if has_sections:
                self.add_error(
                    "sections",
                    "لا يمكن تحديد شعب عندما يكون نطاق الإعلان للصفوف.",
                )

        elif scope == Announcement.Scope.SECTIONS:
            if not has_sections:
                self.add_error(
                    "sections",
                    "يجب تحديد شعبة واحدة على الأقل.",
                )

            if has_grades:
                self.add_error(
                    "grade_levels",
                    "لا يمكن تحديد صفوف عندما يكون نطاق الإعلان للشعب.",
                )

        return cleaned_data


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    form = AnnouncementAdminForm

    list_display = (
        "title",
        "scope",
        "publish_date",
        "expiry_date",
        "created_by",
        "created_at",
    )

    list_filter = (
        "scope",
        "publish_date",
        "expiry_date",
        "created_at",
    )

    search_fields = (
        "title",
        "content",
        "created_by__username",
    )

    ordering = (
        "-publish_date",
        "-created_at",
    )

    readonly_fields = (
        "created_by",
        "created_at",
        "updated_at",
    )

    filter_horizontal = (
        "grade_levels",
        "sections",
    )

    list_select_related = (
        "created_by",
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )