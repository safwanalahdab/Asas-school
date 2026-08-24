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
    StudentScore,
)


class AssessmentSerializer(
    serializers.ModelSerializer,
):
    academic_year = serializers.UUIDField(
        source="section.academic_year_id",
        read_only=True,
    )

    academic_year_display = serializers.CharField(
        source="section.academic_year.name",
        read_only=True,
    )

    grade_level = serializers.UUIDField(
        source="section.grade_level_id",
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source="section.grade_level.name",
        read_only=True,
    )

    section_display = serializers.CharField(
        source="section.name",
        read_only=True,
    )

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

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    published_by_username = serializers.CharField(
        source="published_by.username",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Assessment

        fields = (
            "id",
            "academic_year",
            "academic_year_display",
            "grade_level",
            "grade_level_display",
            "section",
            "section_display",
            "grade_subject",
            "subject",
            "subject_display",
            "term",
            "term_display",
            "title",
            "max_score",
            "assessment_date",
            "status",
            "status_display",
            "created_by",
            "created_by_username",
            "published_by",
            "published_by_username",
            "published_at",
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


class BulkScoreRecordSerializer(
    serializers.Serializer,
):
    enrollment = serializers.PrimaryKeyRelatedField(
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
    records = BulkScoreRecordSerializer(
        many=True,
        allow_empty=False,
    )


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
        choices=Assessment.Status.choices,
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