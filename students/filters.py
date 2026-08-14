from django.db.models import Q, Value
from django.db.models.functions import Concat
from django_filters import rest_framework as filters

from .models import Enrollment, GuardianStudent, Student


class StudentFilter(filters.FilterSet):
    academic_year = filters.UUIDFilter(
        method="filter_enrollment_scope",
    )

    grade_level = filters.UUIDFilter(
        method="filter_enrollment_scope",
    )

    section = filters.UUIDFilter(
        method="filter_enrollment_scope",
    )

    guardian = filters.UUIDFilter(
        field_name="guardian_link__guardian_id",
    )

    search = filters.CharFilter(
        method="filter_search",
    )

    class Meta:
        model = Student

        fields = (
            "is_active",
            "gender",
            "academic_year",
            "grade_level",
            "section",
            "guardian",
        )

    def filter_enrollment_scope(
        self,
        queryset,
        name,
        value,
    ):
        return queryset

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(
            queryset,
        )

        academic_year = self.form.cleaned_data.get(
            "academic_year",
        )

        grade_level = self.form.cleaned_data.get(
            "grade_level",
        )

        section = self.form.cleaned_data.get(
            "section",
        )

        if (
            academic_year
            or grade_level
            or section
        ):
            enrollments = Enrollment.objects.all()

            if academic_year:
                enrollments = enrollments.filter(
                    academic_year_id=academic_year,
                )

            if grade_level:
                enrollments = enrollments.filter(
                    section__grade_level_id=grade_level,
                )

            if section:
                enrollments = enrollments.filter(
                    section_id=section,
                )

            queryset = queryset.filter(
                pk__in=enrollments.values(
                    "student_id",
                ),
            )

        return queryset.distinct()

    def filter_search(
        self,
        queryset,
        name,
        value,
    ):
        value = value.strip()

        if not value:
            return queryset

        queryset = queryset.annotate(
            full_name_search=Concat(
                "first_name",
                Value(" "),
                "last_name",
            ),
            guardian_full_name_search=Concat(
                "guardian_link__guardian__first_name",
                Value(" "),
                "guardian_link__guardian__last_name",
            ),
        )

        return queryset.filter(
            Q(first_name__icontains=value)
            | Q(last_name__icontains=value)
            | Q(full_name_search__icontains=value)
            | Q(
                guardian_full_name_search__icontains=value
            )
            | Q(
                guardian_link__guardian__username__icontains=value
            )
            | Q(
                guardian_link__guardian__email__icontains=value
            )
        ).distinct()


class GuardianStudentFilter(filters.FilterSet):
    class Meta:
        model = GuardianStudent

        fields = (
            "guardian",
            "student",
            "is_active",
        )


class EnrollmentFilter(filters.FilterSet):
    grade_level = filters.UUIDFilter(
        field_name="section__grade_level_id",
    )

    class Meta:
        model = Enrollment

        fields = (
            "student",
            "academic_year",
            "grade_level",
            "section",
        )

        