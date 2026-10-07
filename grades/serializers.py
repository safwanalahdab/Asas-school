import uuid
from decimal import Decimal

from rest_framework import serializers

from academics.models import (
    GradeLevel,
    GradeSubject,
    Section,
    Term,
)
from students.models import Enrollment

from .models import (
    Assessment,
    AssessmentSection,
    StudentScore,
)


class AssessmentSectionSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="section.name", read_only=True)
    published_by_username = serializers.CharField(source="published_by.username", read_only=True, allow_null=True)
    schedule_published_by_username = serializers.CharField(
        source="schedule_published_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = AssessmentSection
        fields = (
            "id", "section", "name",
            "schedule_status", "schedule_published_by",
            "schedule_published_by_username", "schedule_published_at",
            "status", "published_by", "published_by_username", "published_at",
        )
        read_only_fields = fields


class AssessmentSerializer(
    serializers.ModelSerializer,
):
    academic_year = serializers.UUIDField(
        source="grade_subject.academic_year_id",
        read_only=True,
    )

    academic_year_display = serializers.CharField(
        source="grade_subject.academic_year.name",
        read_only=True,
    )

    grade_level = serializers.UUIDField(
        source="grade_subject.grade_level_id",
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source="grade_subject.grade_level.name",
        read_only=True,
    )

    sections = AssessmentSectionSerializer(source="assessment_sections", many=True, read_only=True)

    subject = serializers.UUIDField(
        source="grade_subject.subject_id",
        read_only=True,
    )

    subject_display = serializers.CharField(
        source="grade_subject.subject.name",
        read_only=True,
    )

    term_display = serializers.CharField(
        source="term.get_number_display",
        read_only=True,
    )

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = Assessment

        fields = (
            "id",
            "academic_year",
            "academic_year_display",
            "grade_level",
            "grade_level_display",
            "sections",
            "grade_subject",
            "subject",
            "subject_display",
            "term",
            "term_display",
            "title",
            "max_score",
            "assessment_date",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        )

        read_only_fields = fields


class CreateAssessmentSerializer(
    serializers.Serializer,
):
    section = serializers.PrimaryKeyRelatedField(
        queryset=Section.objects.all(),
    )

    grade_subject = serializers.PrimaryKeyRelatedField(
        queryset=GradeSubject.objects.all(),
    )

    term = serializers.PrimaryKeyRelatedField(
        queryset=Term.objects.all(),
    )

    title = serializers.CharField(
        max_length=150,
        allow_blank=False,
        trim_whitespace=True,
    )

    max_score = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    assessment_date = serializers.DateField()

    allow_duplicate = serializers.BooleanField(
        required=False,
        default=False,
    )


class CreateGradeAssessmentsSerializer(
    serializers.Serializer,
):
    grade_subject = serializers.PrimaryKeyRelatedField(
        queryset=GradeSubject.objects.all(),
    )

    term = serializers.PrimaryKeyRelatedField(
        queryset=Term.objects.all(),
    )

    title = serializers.CharField(
        max_length=150,
        allow_blank=False,
        trim_whitespace=True,
    )

    max_score = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    assessment_date = serializers.DateField()

    allow_duplicate = serializers.BooleanField(
        required=False,
        default=False,
    )


class UpdateAssessmentSerializer(
    serializers.Serializer,
):
    title = serializers.CharField(
        max_length=150,
        allow_blank=False,
        trim_whitespace=True,
        required=False,
    )

    max_score = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )

    assessment_date = serializers.DateField(
        required=False,
    )

    allow_duplicate = serializers.BooleanField(
        required=False,
        default=False,
    )

    def validate(
        self,
        attrs,
    ):
        editable_fields = {
            "title",
            "max_score",
            "assessment_date",
        }

        if not (
            editable_fields
            & set(attrs.keys())
        ):
            raise serializers.ValidationError(
                {
                    "detail": (
                        "يجب إرسال حقل واحد على الأقل "
                        "لتعديل التقييم."
                    )
                }
            )

        return attrs


class StudentScoreSerializer(
    serializers.ModelSerializer,
):
    student = serializers.UUIDField(
        source="enrollment.student_id",
        read_only=True,
    )

    student_display = serializers.CharField(
        source="enrollment.student.full_name",
        read_only=True,
    )

    max_score = serializers.DecimalField(
        source="assessment.max_score",
        max_digits=7,
        decimal_places=2,
        read_only=True,
    )

    updated_by_username = serializers.CharField(
        source="updated_by.username",
        read_only=True,
    )

    class Meta:
        model = StudentScore

        fields = (
            "id",
            "assessment",
            "enrollment",
            "recorded_section",
            "student",
            "student_display",
            "score",
            "max_score",
            "updated_by",
            "updated_by_username",
            "created_at",
            "updated_at",
        )

        read_only_fields = fields


def _enrollment_key(value):
    # Same inputs Django's UUIDField accepts; anything else stays unresolved.
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


class BulkEnrollmentField(serializers.PrimaryKeyRelatedField):
    """Resolve from the batch the root serializer loaded.

    Unloaded values (missing or malformed ids) fall back to the per-item lookup
    so error messages and their positions stay exactly as before.
    """

    def to_internal_value(self, data):
        loaded = getattr(self.root, "loaded_enrollments", None)
        if loaded:
            enrollment = loaded.get(_enrollment_key(data))
            if enrollment is not None:
                return enrollment
        return super().to_internal_value(data)


class BulkScoreRecordSerializer(
    serializers.Serializer,
):
    enrollment = BulkEnrollmentField(
        queryset=Enrollment.objects.all(),
    )

    score = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0"),
        required=True,
        allow_null=True,
    )


class BulkAssessmentScoresSerializer(
    serializers.Serializer,
):
    section = serializers.PrimaryKeyRelatedField(queryset=Section.objects.all())

    records = BulkScoreRecordSerializer(
        many=True,
        allow_empty=False,
    )

    def to_internal_value(self, data):
        self.loaded_enrollments = self._load_enrollments(data)
        return super().to_internal_value(data)

    def _load_enrollments(self, data):
        """Fetch every requested enrollment, with its stage path, in one query."""
        records = data.get("records") if hasattr(data, "get") else None
        if not isinstance(records, list):
            return {}
        keys = {
            _enrollment_key(record.get("enrollment"))
            for record in records
            if hasattr(record, "get")
        } - {None}
        if not keys:
            return {}
        return {
            str(enrollment.pk): enrollment
            for enrollment in Enrollment.objects.select_related(
                "section__grade_level",
            ).filter(pk__in=keys)
        }


class AssessmentScoreRowSerializer(
    serializers.Serializer,
):
    enrollment = serializers.UUIDField(
        read_only=True,
    )

    student = serializers.UUIDField(
        read_only=True,
    )

    student_display = serializers.CharField(
        read_only=True,
    )

    score = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )

    updated_by = serializers.UUIDField(
        read_only=True,
        allow_null=True,
    )

    updated_by_username = serializers.CharField(
        read_only=True,
        allow_null=True,
    )

    updated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
    )


class AssessmentScoresSheetSerializer(
    serializers.Serializer,
):
    assessment = AssessmentSerializer(
        read_only=True,
    )

    records = AssessmentScoreRowSerializer(
        many=True,
        read_only=True,
    )


class PublishSectionSerializer(
    serializers.Serializer,
):
    section = serializers.PrimaryKeyRelatedField(
        queryset=Section.objects.all(),
    )

    term = serializers.PrimaryKeyRelatedField(
        queryset=Term.objects.all(),
    )


class PublishGradeSerializer(
    serializers.Serializer,
):
    grade_level = serializers.PrimaryKeyRelatedField(
        queryset=GradeLevel.objects.all(),
    )

    term = serializers.PrimaryKeyRelatedField(
        queryset=Term.objects.all(),
    )


class PublishResultSerializer(
    serializers.Serializer,
):
    published_count = serializers.IntegerField(
        read_only=True,
    )
    skipped_future_count = serializers.IntegerField(read_only=True)


class AssessmentScheduleActionSerializer(serializers.Serializer):
    assessment = serializers.PrimaryKeyRelatedField(
        queryset=Assessment.objects.all(),
    )
    section = serializers.PrimaryKeyRelatedField(
        queryset=Section.objects.all(),
    )


class AssessmentScheduleResultSerializer(serializers.Serializer):
    assessment = serializers.UUIDField(read_only=True)
    section = serializers.UUIDField(read_only=True)
    schedule_status = serializers.ChoiceField(
        choices=AssessmentSection.ScheduleStatus.choices,
        read_only=True,
    )
    schedule_published_by = serializers.UUIDField(read_only=True, allow_null=True)
    schedule_published_at = serializers.DateTimeField(read_only=True, allow_null=True)
    result_status = serializers.ChoiceField(
        choices=AssessmentSection.Status.choices,
        read_only=True,
    )


class StudentResultsQuerySerializer(
    serializers.Serializer,
):
    enrollment = serializers.PrimaryKeyRelatedField(
        queryset=Enrollment.objects.all(),
    )

    term = serializers.PrimaryKeyRelatedField(
        queryset=Term.objects.all(),
    )


class StudentResultAssessmentSerializer(
    serializers.Serializer,
):
    assessment = serializers.UUIDField(
        read_only=True,
    )

    title = serializers.CharField(
        read_only=True,
    )

    score = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )

    max_score = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        read_only=True,
    )

    assessment_date = serializers.DateField(
        read_only=True,
    )

    status = serializers.ChoiceField(
        choices=AssessmentSection.Status.choices,
        read_only=True,
    )


class StudentSubjectResultSerializer(
    serializers.Serializer,
):
    grade_subject = serializers.UUIDField(
        read_only=True,
    )

    subject = serializers.UUIDField(
        read_only=True,
    )

    subject_display = serializers.CharField(
        read_only=True,
    )

    assessments = StudentResultAssessmentSerializer(
        many=True,
        read_only=True,
    )

    total_score = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    total_max_score = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    is_complete = serializers.BooleanField(
        read_only=True,
    )


class StudentTermResultsSerializer(
    serializers.Serializer,
):
    enrollment = serializers.UUIDField(
        read_only=True,
    )

    student = serializers.UUIDField(
        read_only=True,
    )

    student_display = serializers.CharField(
        read_only=True,
    )

    term = serializers.UUIDField(
        read_only=True,
    )

    term_display = serializers.CharField(
        read_only=True,
    )

    subjects = StudentSubjectResultSerializer(
        many=True,
        read_only=True,
    )
