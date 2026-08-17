from django.utils import timezone
from rest_framework import serializers

from .models import Announcement


class AnnouncementSerializer(serializers.ModelSerializer):
    scope_display = serializers.CharField(
        source="get_scope_display",
        read_only=True,
    )

    is_active = serializers.SerializerMethodField()

    grade_levels_display = serializers.SerializerMethodField()

    sections_display = serializers.SerializerMethodField()

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = Announcement

        fields = (
            "id",

            "scope",
            "scope_display",

            "grade_levels",
            "grade_levels_display",

            "sections",
            "sections_display",

            "title",
            "content",

            "publish_date",
            "expiry_date",
            "is_active",

            "attachment",

            "created_by",
            "created_by_username",

            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_by",
            "created_at",
            "updated_at",
        )

    def get_is_active(self, obj):
        today = timezone.localdate()

        if obj.publish_date > today:
            return False

        if (
            obj.expiry_date
            and obj.expiry_date < today
        ):
            return False

        return True

    def get_grade_levels_display(self, obj):
        return [
            {
                "id": str(grade.id),
                "name": grade.name,
            }
            for grade in obj.grade_levels.all()
        ]

    def get_sections_display(self, obj):
        return [
            {
                "id": str(section.id),
                "name": section.name,
                "grade_level": {
                    "id": str(section.grade_level_id),
                    "name": section.grade_level.name,
                },
            }
            for section in obj.sections.all()
        ]

    def validate(self, attrs):
        instance = self.instance

        scope = attrs.get(
            "scope",
            getattr(instance, "scope", None),
        )

        grade_levels = attrs.get("grade_levels")

        if grade_levels is None:
            grade_levels = (
                list(instance.grade_levels.all())
                if instance
                else []
            )

        sections = attrs.get("sections")

        if sections is None:
            sections = (
                list(instance.sections.all())
                if instance
                else []
            )

        publish_date = attrs.get(
            "publish_date",
            getattr(instance, "publish_date", None),
        )

        expiry_date = attrs.get(
            "expiry_date",
            getattr(instance, "expiry_date", None),
        )

        errors = {}

        if scope == Announcement.Scope.ALL:
            if grade_levels:
                errors["grade_levels"] = (
                    "لا يمكن تحديد صفوف عندما يكون الإعلان لجميع المدرسة."
                )

            if sections:
                errors["sections"] = (
                    "لا يمكن تحديد شعب عندما يكون الإعلان لجميع المدرسة."
                )

        elif scope == Announcement.Scope.GRADES:
            if not grade_levels:
                errors["grade_levels"] = (
                    "يجب تحديد صف واحد على الأقل."
                )

            if sections:
                errors["sections"] = (
                    "لا يمكن تحديد شعب عندما يكون نطاق الإعلان للصفوف."
                )

        elif scope == Announcement.Scope.SECTIONS:
            if not sections:
                errors["sections"] = (
                    "يجب تحديد شعبة واحدة على الأقل."
                )

            if grade_levels:
                errors["grade_levels"] = (
                    "لا يمكن تحديد صفوف عندما يكون نطاق الإعلان للشعب."
                )

        if (
            publish_date
            and expiry_date
            and expiry_date < publish_date
        ):
            errors["expiry_date"] = (
                "لا يمكن أن يسبق تاريخ انتهاء الإعلان تاريخ نشره."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs