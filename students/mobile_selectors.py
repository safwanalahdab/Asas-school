from django.db.models import Prefetch
from rest_framework.exceptions import NotFound

from academics.models import AcademicYear

from .models import Enrollment, Student


def _current_enrollment_prefetch():
    """
    يجلب تسجيل الطالب في السنة الدراسية الفعالة فقط.

    نستخدم to_attr حتى لا نضع التسجيلات الحالية
    داخل enrollments العادية، وحتى يكون واضحًا
    للـSerializer لاحقًا أن هذه القائمة تحتوي
    التسجيل الحالي فقط.
    """
    return Prefetch(
        "enrollments",
        queryset=(
            Enrollment.objects.filter(
                academic_year__status=AcademicYear.Status.ACTIVE,
            )
            .select_related(
                "academic_year",
                "section__grade_level",
            )
        ),
        to_attr="mobile_current_enrollments",
    )


def get_guardian_children_queryset(*, guardian):
    """
    يعيد الطلاب الفعالين المرتبطين بولي الأمر الحالي
    من خلال علاقة GuardianStudent فعالة فقط.

    ويحمّل التسجيل الحالي مسبقًا لتجنب N+1 Queries.
    """
    return (
        Student.objects.filter(
            is_active=True,
            guardian_link__guardian=guardian,
            guardian_link__is_active=True,
        )
        .prefetch_related(
            _current_enrollment_prefetch(),
        )
        .order_by(
            "first_name",
            "last_name",
        )
    )


def get_guardian_child_or_404(
    *,
    guardian,
    student_id,
):
    """
    يعيد طالبًا واحدًا فقط إذا كان ولي الأمر الحالي
    يملك حق الوصول إليه.

    لا نفرق في الخطأ بين:
    - طالب غير موجود.
    - طالب تابع لعائلة أخرى.
    - علاقة GuardianStudent غير فعالة.
    - طالب غير فعال.

    وذلك لمنع كشف معلومات عن الطلاب الآخرين.
    """
    student = (
        get_guardian_children_queryset(
            guardian=guardian,
        )
        .filter(
            id=student_id,
        )
        .first()
    )

    if student is None:
        raise NotFound(
            {
                "code": "MOBILE_CHILD_NOT_FOUND",
                "detail": "لم يتم العثور على الطالب المطلوب.",
            }
        )

    return student