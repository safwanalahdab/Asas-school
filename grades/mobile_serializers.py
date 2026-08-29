from rest_framework import serializers

from academics.models import Term


class MobileGradesQuerySerializer(serializers.Serializer):
    term = serializers.UUIDField(required=False)

    def validate_term(self, value):
        try:
            term = Term.objects.get(pk=value)
        except Term.DoesNotExist as exc:
            raise serializers.ValidationError(
                "الفصل الدراسي المحدد غير موجود."
            ) from exc

        academic_year = self.context["academic_year"]
        if term.academic_year_id != academic_year.id:
            raise serializers.ValidationError(
                "الفصل الدراسي المحدد لا يتبع السنة الدراسية الحالية للطالب."
            )
        return term


class MobileGradeStudentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()


class MobileGradeAcademicYearSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MobileGradeSubjectSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MobileAssessmentResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    assessment_date = serializers.DateField()
    score = serializers.DecimalField(max_digits=7, decimal_places=2, allow_null=True)
    max_score = serializers.DecimalField(max_digits=7, decimal_places=2)


class MobileSubjectGradesSerializer(serializers.Serializer):
    grade_subject = serializers.UUIDField()
    subject = MobileGradeSubjectSummarySerializer()
    assessments = MobileAssessmentResultSerializer(many=True)
    total_score = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_max_score = serializers.DecimalField(max_digits=12, decimal_places=2)
    percentage = serializers.DecimalField(
        max_digits=7, decimal_places=2, allow_null=True
    )
    is_complete = serializers.BooleanField()


class MobileTermGradesSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.IntegerField()
    number_display = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    subjects = MobileSubjectGradesSerializer(many=True)


class MobileGradesDataSerializer(serializers.Serializer):
    student = MobileGradeStudentSerializer()
    academic_year = MobileGradeAcademicYearSerializer(allow_null=True)
    terms = MobileTermGradesSerializer(many=True)


class MobileGradesMetaSerializer(serializers.Serializer):
    requester_role = serializers.JSONField(allow_null=True)


class MobileGradesResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="MOBILE_CHILD_GRADES_RETRIEVED")
    message = serializers.CharField()
    data = MobileGradesDataSerializer()
    meta = MobileGradesMetaSerializer()


class MobileGradesErrorSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    code = serializers.CharField()
    message = serializers.CharField()
    errors = serializers.JSONField(required=False)
    meta = MobileGradesMetaSerializer()
