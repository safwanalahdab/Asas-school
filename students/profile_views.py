from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import ActionBusinessPermission, PasswordChangeGate
from behavior.permissions import IsWebClientToken
from config.api_responses import ArabicApiResponseMixin
from finance.models import Payment, StudentDiscount
from finance.services import calculate_account_totals
from academics.supervisor_academic_scope import filter_students_by_supervisor_scope

from .profile_pagination import paginate_profile_queryset
from .profile_permissions import CanViewStudentProfileRole
from .models import Student
from .profile_selectors import (
    get_attendance_data,
    get_behavior_data,
    get_financial_account,
    get_grade_records,
    get_profile_academic_year,
    get_profile_enrollment,
    get_profile_guardians,
    get_profile_health,
    get_profile_student,
)
from .profile_serializers import (
    ProfileAttendanceRecordSerializer,
    ProfileBehaviorNoteSerializer,
    ProfileDiscountSerializer,
    ProfileGradeSerializer,
    ProfilePaymentSerializer,
    StudentProfileErrorSerializer,
    StudentProfileResponseSerializer,
    StudentProfileSerializer,
)


PROFILE_QUERY_PARAMETERS = [
    OpenApiParameter(
        name="student_id",
        type=str,
        location=OpenApiParameter.PATH,
        required=True,
        description="معرّف UUID للطالب.",
    ),
    OpenApiParameter(
        name="academic_year",
        type=str,
        location=OpenApiParameter.QUERY,
        required=False,
        description="معرّف السنة الدراسية. عند حذفه تُستخدم السنة الفعالة.",
    ),
]

for collection in ("attendance", "grades", "behavior", "payments", "discounts"):
    PROFILE_QUERY_PARAMETERS.extend(
        [
            OpenApiParameter(
                name=f"{collection}_page",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="رقم الصفحة، والقيمة الافتراضية 1.",
            ),
            OpenApiParameter(
                name=f"{collection}_page_size",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="حجم الصفحة من 1 إلى 100، والقيمة الافتراضية 10.",
            ),
        ]
    )


def _serialized_page(page, serializer_class):
    return {
        **page,
        "results": serializer_class(page["results"], many=True).data,
    }


class StudentProfileView(ArabicApiResponseMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
        CanViewStudentProfileRole,
    ]
    method_permissions = {"get": "students.view_student_profile"}
    http_method_names = ["get", "head", "options"]
    response_messages = {
        "get": (
            "STUDENT_PROFILE_RETRIEVED",
            "تم جلب الملف الشامل للطالب بنجاح.",
        )
    }

    @extend_schema(
        operation_id="students_retrieve_comprehensive_profile",
        description=(
            "واجهة ويب إدارية للقراءة فقط تعرض الملف الشامل للطالب. "
            "تتطلب الصلاحية students.view_student_profile، وعند عدم إرسال "
            "academic_year تُستخدم السنة الدراسية الفعالة."
        ),
        parameters=PROFILE_QUERY_PARAMETERS,
        responses={
            200: StudentProfileResponseSerializer,
            400: StudentProfileErrorSerializer,
            401: StudentProfileErrorSerializer,
            403: StudentProfileErrorSerializer,
            404: StudentProfileErrorSerializer,
            405: StudentProfileErrorSerializer,
        },
    )
    def get(self, request, student_id):
        eligible_students = filter_students_by_supervisor_scope(
            Student.objects.all(), request.user
        )
        student = get_profile_student(student_id, queryset=eligible_students)
        academic_year = get_profile_academic_year(
            request.query_params.get("academic_year")
        )
        enrollment = get_profile_enrollment(student, academic_year)
        guardians = get_profile_guardians(student)
        health_profile = get_profile_health(student)

        attendance_records, attendance_summary = get_attendance_data(enrollment)
        grade_records = get_grade_records(enrollment)
        behavior_notes, behavior_summary = get_behavior_data(enrollment)
        financial_account = get_financial_account(enrollment)

        attendance_page = paginate_profile_queryset(
            attendance_records, request.query_params, "attendance"
        )
        grades_page = paginate_profile_queryset(
            grade_records, request.query_params, "grades"
        )
        behavior_page = paginate_profile_queryset(
            behavior_notes, request.query_params, "behavior"
        )

        if financial_account is None:
            payments = Payment.objects.none()
            discounts = StudentDiscount.objects.none()
            finance_summary = None
        else:
            payments = financial_account.payments.order_by("-paid_at", "-created_at")
            discounts = financial_account.discounts.order_by("-created_at")
            finance_summary = calculate_account_totals(financial_account)

        payments_page = paginate_profile_queryset(
            payments, request.query_params, "payments"
        )
        discounts_page = paginate_profile_queryset(
            discounts, request.query_params, "discounts"
        )

        data = {
            "student": student,
            "guardians": guardians,
            "health_profile": health_profile,
            "academic_year": academic_year,
            "enrollment": enrollment,
            "attendance": {
                "summary": attendance_summary,
                "records": _serialized_page(
                    attendance_page, ProfileAttendanceRecordSerializer
                ),
            },
            "grades": _serialized_page(grades_page, ProfileGradeSerializer),
            "behavior": {
                "summary": behavior_summary,
                "notes": _serialized_page(
                    behavior_page, ProfileBehaviorNoteSerializer
                ),
            },
            "finance": {
                "account": financial_account,
                "summary": finance_summary,
                "payments": _serialized_page(
                    payments_page, ProfilePaymentSerializer
                ),
                "discounts": _serialized_page(
                    discounts_page, ProfileDiscountSerializer
                ),
            },
        }
        return Response(
            StudentProfileSerializer(data).data,
            status=status.HTTP_200_OK,
        )
