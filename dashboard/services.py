from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    Sum,
    Value,
    When,
)
from django.db.models.functions import (
    Coalesce,
    Round,
)
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from academics.models import (
    AcademicYear,
    Section,
    Term,
)
from appointments.models import AppointmentRequest
from finance.models import (
    Payment,
    StudentDiscount,
    StudentFinancialAccount,
)
from finance.utils import quantize_usd
from school_requests.models import SchoolRequest
from students.models import Enrollment


User = get_user_model()


ZERO_USD = Decimal("0.00")
HUNDRED = Decimal("100")

MONEY_FIELD = DecimalField(
    max_digits=18,
    decimal_places=2,
)


def _validate_scope(
    *,
    academic_year,
    grade_level=None,
    section=None,
):
    if section is None:
        return

    if section.academic_year_id != academic_year.id:
        raise ValidationError(
            {
                "section": (
                    "الشعبة المحددة لا تتبع "
                    "السنة الدراسية المحددة."
                )
            }
        )

    if (
        grade_level is not None
        and section.grade_level_id != grade_level.id
    ):
        raise ValidationError(
            {
                "section": (
                    "الشعبة المحددة لا تتبع "
                    "الصف المحدد."
                )
            }
        )


def _build_accounts_queryset(
    *,
    academic_year,
    grade_level=None,
    section=None,
):
    queryset = (
        StudentFinancialAccount.objects
        .filter(
            enrollment__academic_year=academic_year,
        )
    )

    if grade_level is not None:
        queryset = queryset.filter(
            enrollment__section__grade_level=(
                grade_level
            ),
        )

    if section is not None:
        queryset = queryset.filter(
            enrollment__section=section,
        )

    return queryset


def _get_finance_totals(
    *,
    academic_year,
    grade_level=None,
    section=None,
):
    accounts = _build_accounts_queryset(
        academic_year=academic_year,
        grade_level=grade_level,
        section=section,
    )

    total_tuition_usd = accounts.aggregate(
        total=Coalesce(
            Sum(
                "tuition_plan__base_tuition_usd",
                output_field=MONEY_FIELD,
            ),
            Value(ZERO_USD),
            output_field=MONEY_FIELD,
        )
    )["total"]

    discount_amount_expression = Case(
        When(
            discount_type=(
                StudentDiscount
                .DiscountType
                .PERCENTAGE
            ),
            then=Round(
                ExpressionWrapper(
                    F(
                        "account__tuition_plan__base_tuition_usd"
                    )
                    * F("value")
                    / Value(HUNDRED),
                    output_field=MONEY_FIELD,
                ),
                precision=2,
            ),
        ),
        When(
            discount_type=(
                StudentDiscount
                .DiscountType
                .FIXED
            ),
            then=F("equivalent_usd"),
        ),
        default=Value(ZERO_USD),
        output_field=MONEY_FIELD,
    )

    total_discounts_usd = (
        StudentDiscount.objects
        .filter(
            account__in=accounts,
            is_cancelled=False,
        )
        .aggregate(
            total=Coalesce(
                Sum(
                    discount_amount_expression,
                    output_field=MONEY_FIELD,
                ),
                Value(ZERO_USD),
                output_field=MONEY_FIELD,
            )
        )
    )["total"]

    total_paid_usd = (
        Payment.objects
        .filter(
            account__in=accounts,
            is_cancelled=False,
        )
        .aggregate(
            total=Coalesce(
                Sum(
                    "equivalent_usd",
                    output_field=MONEY_FIELD,
                ),
                Value(ZERO_USD),
                output_field=MONEY_FIELD,
            )
        )
    )["total"]

    total_tuition_usd = quantize_usd(
        total_tuition_usd
    )

    total_discounts_usd = quantize_usd(
        total_discounts_usd
    )

    total_paid_usd = quantize_usd(
        total_paid_usd
    )

    total_remaining_usd = quantize_usd(
        total_tuition_usd
        - total_discounts_usd
        - total_paid_usd
    )

    return {
        "total_tuition_usd": total_tuition_usd,
        "total_discounts_usd": (
            total_discounts_usd
        ),
        "total_paid_usd": total_paid_usd,
        "total_remaining_usd": (
            total_remaining_usd
        ),
    }


def get_dashboard_overview(
    *,
    academic_year=None,
    grade_level=None,
    section=None,
):
    today = timezone.localdate()

    active_year = (
        AcademicYear.objects
        .filter(
            status=AcademicYear.Status.ACTIVE,
        )
        .first()
    )

    selected_year = (
        academic_year
        if academic_year is not None
        else active_year
    )

    active_teachers_count = (
        User.objects
        .filter(
            role=User.Role.TEACHER,
            is_active=True,
        )
        .count()
    )

    pending_appointments_count = (
        AppointmentRequest.objects
        .filter(
            status=AppointmentRequest.Status.PENDING,
        )
        .count()
    )

    unanswered_guardian_requests_count = (
        SchoolRequest.objects
        .filter(
            status=SchoolRequest.Status.NEW,
            request_type__in=[
                SchoolRequest.RequestType.COMPLAINT,
                SchoolRequest.RequestType.INQUIRY,
            ],
        )
        .count()
    )

    current_term = None

    if active_year is not None:
        current_term = (
            Term.objects
            .filter(
                academic_year=active_year,
                start_date__lte=today,
                end_date__gte=today,
            )
            .order_by(
                "number",
            )
            .first()
        )

    current_term_display = None

    if current_term is not None:
        current_term_display = (
            f"الفصل "
            f"{current_term.get_number_display()}"
        )

    if selected_year is None:
        return {
            "students_count": 0,
            "active_teachers_count": (
                active_teachers_count
            ),
            "sections_count": 0,
            "pending_appointments_count": (
                pending_appointments_count
            ),
            "unanswered_guardian_requests_count": (
                unanswered_guardian_requests_count
            ),
            "total_tuition_usd": ZERO_USD,
            "total_discounts_usd": ZERO_USD,
            "total_paid_usd": ZERO_USD,
            "total_remaining_usd": ZERO_USD,
            "active_academic_year": None,
            "current_term": current_term_display,
            "today": today,
        }

    _validate_scope(
        academic_year=selected_year,
        grade_level=grade_level,
        section=section,
    )

    enrollments = (
        Enrollment.objects
        .filter(
            academic_year=selected_year,
        )
    )

    sections = (
        Section.objects
        .filter(
            academic_year=selected_year,
        )
    )

    if grade_level is not None:
        enrollments = enrollments.filter(
            section__grade_level=grade_level,
        )

        sections = sections.filter(
            grade_level=grade_level,
        )

    if section is not None:
        enrollments = enrollments.filter(
            section=section,
        )

        sections = sections.filter(
            pk=section.pk,
        )

    students_count = (
        enrollments
        .values(
            "student_id",
        )
        .distinct()
        .count()
    )

    sections_count = sections.count()

    finance_totals = _get_finance_totals(
        academic_year=selected_year,
        grade_level=grade_level,
        section=section,
    )

    return {
        "students_count": students_count,
        "active_teachers_count": (
            active_teachers_count
        ),
        "sections_count": sections_count,
        "pending_appointments_count": (
            pending_appointments_count
        ),
        "unanswered_guardian_requests_count": (
            unanswered_guardian_requests_count
        ),
        **finance_totals,
        "active_academic_year": (
            active_year.name
            if active_year is not None
            else None
        ),
        "current_term": current_term_display,
        "today": today,
    }