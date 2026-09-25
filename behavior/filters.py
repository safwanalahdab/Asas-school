from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from .models import BehaviorNote, StudentPointEntry


class BehaviorNoteFilter(filters.FilterSet):
    occurred_from = filters.DateFilter(
        field_name="occurred_on",
        lookup_expr="gte",
    )

    occurred_to = filters.DateFilter(
        field_name="occurred_on",
        lookup_expr="lte",
    )

    class Meta:
        model = BehaviorNote
        fields = (
            "note_type",
            "enrollment",
            "created_by",
        )


class StudentPointEntryFilter(filters.FilterSet):
    student = filters.UUIDFilter(
        field_name="enrollment__student_id",
    )
    academic_year = filters.UUIDFilter(
        field_name="enrollment__academic_year_id",
    )
    section = filters.UUIDFilter(
        field_name="enrollment__section_id",
    )
    date_from = filters.DateFilter(
        field_name="occurred_on",
        lookup_expr="gte",
    )
    date_to = filters.DateFilter(
        field_name="occurred_on",
        lookup_expr="lte",
    )

    class Meta:
        model = StudentPointEntry
        fields = (
            "enrollment",
            "student",
            "academic_year",
            "section",
            "date_from",
            "date_to",
        )

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        date_from = self.form.cleaned_data.get("date_from")
        date_to = self.form.cleaned_data.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError({
                "date_to": "يجب أن يكون تاريخ النهاية مساويًا لتاريخ البداية أو بعده."
            })
        return queryset
