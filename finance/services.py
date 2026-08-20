from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from students.models import Enrollment

from .models import (
    GradeTuitionPlan,
    MoneyCurrency,
    Payment,
    StudentDiscount,
    StudentFinancialAccount,
)
from .utils import (
    convert_syp_to_usd,
    quantize_usd,
)


ZERO_USD = Decimal("0.00")
HUNDRED = Decimal("100")


def ensure_financial_account_for_enrollment(
    *,
    enrollment,
    actor,
):
    tuition_plan = (
        GradeTuitionPlan.objects
        .filter(
            academic_year=enrollment.academic_year,
            grade_level=enrollment.section.grade_level,
        )
        .first()
    )

    if tuition_plan is None:
        return None

    account, created = (
        StudentFinancialAccount.objects
        .get_or_create(
            enrollment=enrollment,
            defaults={
                "tuition_plan": tuition_plan,
                "created_by": actor,
            },
        )
    )

    if (
        not created
        and account.tuition_plan_id
        != tuition_plan.id
    ):
        raise ValidationError(
            {
                "enrollment": (
                    "الحساب المالي الحالي مرتبط "
                    "بخطة رسوم مختلفة."
                )
            }
        )

    return account


@transaction.atomic
def create_missing_financial_accounts_for_plan(
    *,
    tuition_plan,
    actor,
):
    enrollments = (
        Enrollment.objects
        .filter(
            academic_year=(
                tuition_plan.academic_year
            ),
            section__grade_level=(
                tuition_plan.grade_level
            ),
        )
        .select_related(
            "academic_year",
            "section",
            "section__grade_level",
        )
    )

    created_count = 0

    for enrollment in enrollments:
        account, created = (
            StudentFinancialAccount.objects
            .get_or_create(
                enrollment=enrollment,
                defaults={
                    "tuition_plan": tuition_plan,
                    "created_by": actor,
                },
            )
        )

        if (
            not created
            and account.tuition_plan_id
            != tuition_plan.id
        ):
            raise ValidationError(
                {
                    "tuition_plan": (
                        "يوجد حساب مالي لطالب "
                        "مرتبط بخطة رسوم مختلفة."
                    )
                }
            )

        if created:
            created_count += 1

    return created_count


def calculate_discount_usd(
    discount,
    *,
    base_tuition_usd,
):
    if (
        discount.discount_type
        == StudentDiscount.DiscountType.PERCENTAGE
    ):
        discount_usd = (
            base_tuition_usd
            * discount.value
            / HUNDRED
        )

        return quantize_usd(
            discount_usd
        )

    if discount.equivalent_usd is None:
        raise ValidationError(
            {
                "discount": (
                    "الخصم الثابت لا يحتوي "
                    "على قيمة مكافئة بالدولار."
                )
            }
        )

    return quantize_usd(
        discount.equivalent_usd
    )


def calculate_account_totals(
    account,
    *,
    base_tuition_usd=None,
):
    if base_tuition_usd is None:
        base_tuition_usd = (
            account
            .tuition_plan
            .base_tuition_usd
        )

    base_tuition_usd = quantize_usd(
        base_tuition_usd
    )

    total_discounts_usd = ZERO_USD

    active_discounts = (
        account.discounts
        .filter(
            is_cancelled=False,
        )
    )

    for discount in active_discounts:
        total_discounts_usd += (
            calculate_discount_usd(
                discount,
                base_tuition_usd=(
                    base_tuition_usd
                ),
            )
        )

    total_discounts_usd = quantize_usd(
        total_discounts_usd
    )

    net_tuition_usd = quantize_usd(
        base_tuition_usd
        - total_discounts_usd
    )

    total_paid_usd = ZERO_USD

    active_payments = (
        account.payments
        .filter(
            is_cancelled=False,
        )
    )

    for payment in active_payments:
        total_paid_usd += (
            payment.equivalent_usd
        )

    total_paid_usd = quantize_usd(
        total_paid_usd
    )

    remaining_usd = quantize_usd(
        net_tuition_usd
        - total_paid_usd
    )

    return {
        "base_tuition_usd": (
            base_tuition_usd
        ),
        "total_discounts_usd": (
            total_discounts_usd
        ),
        "net_tuition_usd": (
            net_tuition_usd
        ),
        "total_paid_usd": (
            total_paid_usd
        ),
        "remaining_usd": (
            remaining_usd
        ),
    }


@transaction.atomic
def update_tuition_plan_price(
    *,
    tuition_plan,
    new_base_tuition_usd,
):
    if new_base_tuition_usd <= 0:
        raise ValidationError(
            {
                "base_tuition_usd": (
                    "يجب أن يكون سعر الصف "
                    "أكبر من صفر."
                )
            }
        )

    new_base_tuition_usd = quantize_usd(
        new_base_tuition_usd
    )

    locked_plan = (
        GradeTuitionPlan.objects
        .select_for_update()
        .get(
            pk=tuition_plan.pk,
        )
    )

    accounts = (
        StudentFinancialAccount.objects
        .select_for_update()
        .filter(
            tuition_plan=locked_plan,
        )
        .select_related(
            "enrollment",
            "enrollment__student",
            "tuition_plan",
        )
    )

    for account in accounts:
        totals = calculate_account_totals(
            account,
            base_tuition_usd=(
                new_base_tuition_usd
            ),
        )

        student_name = (
            account
            .enrollment
            .student
            .full_name
        )

        if (
            totals["total_discounts_usd"]
            > new_base_tuition_usd
        ):
            raise ValidationError(
                {
                    "base_tuition_usd": (
                        "لا يمكن تعديل سعر الصف "
                        f"إلى {new_base_tuition_usd} USD، "
                        f"لأن خصومات الطالب "
                        f"{student_name} "
                        "أصبحت أكبر من القسط."
                    )
                }
            )

        if (
            totals["total_paid_usd"]
            > totals["net_tuition_usd"]
        ):
            raise ValidationError(
                {
                    "base_tuition_usd": (
                        "لا يمكن تخفيض سعر الصف "
                        f"إلى {new_base_tuition_usd} USD، "
                        f"لأن الطالب {student_name} "
                        "دفع مبلغًا أكبر من القسط "
                        "الجديد بعد الخصومات."
                    )
                }
            )

    locked_plan.base_tuition_usd = (
        new_base_tuition_usd
    )

    locked_plan.save(
        update_fields=[
            "base_tuition_usd",
            "updated_at",
        ]
    )

    return locked_plan


@transaction.atomic
def create_student_discount(
    *,
    account,
    discount_type,
    value,
    currency="",
    exchange_rate_syp_per_usd=None,
    reason="",
    actor,
):
    if value <= 0:
        raise ValidationError(
            {
                "value": (
                    "يجب أن تكون قيمة الخصم "
                    "أكبر من صفر."
                )
            }
        )

    locked_account = (
        StudentFinancialAccount.objects
        .select_for_update()
        .select_related(
            "tuition_plan",
        )
        .get(
            pk=account.pk,
        )
    )

    equivalent_usd = None

    if (
        discount_type
        == StudentDiscount.DiscountType.PERCENTAGE
    ):
        if value > HUNDRED:
            raise ValidationError(
                {
                    "value": (
                        "لا يمكن أن تتجاوز "
                        "نسبة الخصم 100%."
                    )
                }
            )

        currency = ""
        exchange_rate_syp_per_usd = None

        discount_usd = quantize_usd(
            locked_account
            .tuition_plan
            .base_tuition_usd
            * value
            / HUNDRED
        )

    elif (
        discount_type
        == StudentDiscount.DiscountType.FIXED
    ):
        if currency == MoneyCurrency.USD:
            exchange_rate_syp_per_usd = None
            equivalent_usd = quantize_usd(
                value
            )

        elif currency == MoneyCurrency.SYP:
            if (
                exchange_rate_syp_per_usd
                is None
                or exchange_rate_syp_per_usd <= 0
            ):
                raise ValidationError(
                    {
                        "exchange_rate_syp_per_usd": (
                            "يجب إدخال سعر صرف "
                            "صحيح عند إضافة خصم "
                            "بالليرة السورية."
                        )
                    }
                )

            equivalent_usd = (
                convert_syp_to_usd(
                    value,
                    exchange_rate_syp_per_usd,
                )
            )

        else:
            raise ValidationError(
                {
                    "currency": (
                        "يجب تحديد عملة صحيحة "
                        "للخصم الثابت."
                    )
                }
            )

        discount_usd = equivalent_usd

    else:
        raise ValidationError(
            {
                "discount_type": (
                    "نوع الخصم غير صالح."
                )
            }
        )

    totals = calculate_account_totals(
        locked_account
    )

    new_total_discounts_usd = (
        totals["total_discounts_usd"]
        + discount_usd
    )

    new_total_discounts_usd = (
        quantize_usd(
            new_total_discounts_usd
        )
    )

    if (
        new_total_discounts_usd
        > totals["base_tuition_usd"]
    ):
        raise ValidationError(
            {
                "value": (
                    "إجمالي الخصومات لا يمكن "
                    "أن يتجاوز قيمة القسط."
                )
            }
        )

    new_net_tuition_usd = quantize_usd(
        totals["base_tuition_usd"]
        - new_total_discounts_usd
    )

    if (
        totals["total_paid_usd"]
        > new_net_tuition_usd
    ):
        raise ValidationError(
            {
                "value": (
                    "لا يمكن إضافة هذا الخصم، "
                    "لأن المبلغ المدفوع أصبح "
                    "أكبر من القسط بعد الخصم."
                )
            }
        )

    return StudentDiscount.objects.create(
        account=locked_account,
        discount_type=discount_type,
        value=value,
        currency=currency,
        exchange_rate_syp_per_usd=(
            exchange_rate_syp_per_usd
        ),
        equivalent_usd=equivalent_usd,
        reason=reason,
        created_by=actor,
    )


@transaction.atomic
def cancel_student_discount(
    *,
    discount,
    actor,
    cancellation_reason,
):
    cancellation_reason = (
        cancellation_reason.strip()
    )

    if not cancellation_reason:
        raise ValidationError(
            {
                "cancellation_reason": (
                    "يجب إدخال سبب إلغاء الخصم."
                )
            }
        )

    locked_account = (
        StudentFinancialAccount.objects
        .select_for_update()
        .get(
            pk=discount.account_id,
        )
    )

    locked_discount = (
        StudentDiscount.objects
        .select_for_update()
        .get(
            pk=discount.pk,
            account=locked_account,
        )
    )

    if locked_discount.is_cancelled:
        raise ValidationError(
            {
                "discount": (
                    "تم إلغاء هذا الخصم مسبقًا."
                )
            }
        )

    locked_discount.is_cancelled = True
    locked_discount.cancellation_reason = (
        cancellation_reason
    )
    locked_discount.cancelled_by = actor
    locked_discount.cancelled_at = (
        timezone.now()
    )

    locked_discount.save(
        update_fields=[
            "is_cancelled",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
        ]
    )

    return locked_discount


@transaction.atomic
def record_payment(
    *,
    account,
    currency,
    amount,
    exchange_rate_syp_per_usd=None,
    actor,
):
    if amount <= 0:
        raise ValidationError(
            {
                "amount": (
                    "يجب أن تكون قيمة الدفعة "
                    "أكبر من صفر."
                )
            }
        )

    locked_account = (
        StudentFinancialAccount.objects
        .select_for_update()
        .select_related(
            "tuition_plan",
        )
        .get(
            pk=account.pk,
        )
    )

    if currency == MoneyCurrency.USD:
        exchange_rate_syp_per_usd = None
        equivalent_usd = quantize_usd(
            amount
        )

    elif currency == MoneyCurrency.SYP:
        if (
            exchange_rate_syp_per_usd
            is None
            or exchange_rate_syp_per_usd <= 0
        ):
            raise ValidationError(
                {
                    "exchange_rate_syp_per_usd": (
                        "يجب إدخال سعر صرف "
                        "صحيح عند الدفع "
                        "بالليرة السورية."
                    )
                }
            )

        equivalent_usd = convert_syp_to_usd(
            amount,
            exchange_rate_syp_per_usd,
        )

    else:
        raise ValidationError(
            {
                "currency": (
                    "عملة الدفع غير صالحة."
                )
            }
        )

    totals = calculate_account_totals(
        locked_account
    )

    remaining_usd = totals[
        "remaining_usd"
    ]

    if remaining_usd <= ZERO_USD:
        raise ValidationError(
            {
                "amount": (
                    "الحساب المالي مسدد بالكامل."
                )
            }
        )

    if equivalent_usd > remaining_usd:
        raise ValidationError(
            {
                "amount": (
                    "قيمة الدفعة تتجاوز "
                    "المبلغ المتبقي."
                )
            }
        )

    return Payment.objects.create(
        account=locked_account,
        currency=currency,
        amount=amount,
        exchange_rate_syp_per_usd=(
            exchange_rate_syp_per_usd
        ),
        equivalent_usd=equivalent_usd,
        recorded_by=actor,
    )


@transaction.atomic
def cancel_payment(
    *,
    payment,
    actor,
    cancellation_reason,
):
    cancellation_reason = (
        cancellation_reason.strip()
    )

    if not cancellation_reason:
        raise ValidationError(
            {
                "cancellation_reason": (
                    "يجب إدخال سبب إلغاء الدفعة."
                )
            }
        )

    locked_account = (
        StudentFinancialAccount.objects
        .select_for_update()
        .get(
            pk=payment.account_id,
        )
    )

    locked_payment = (
        Payment.objects
        .select_for_update()
        .get(
            pk=payment.pk,
            account=locked_account,
        )
    )

    if locked_payment.is_cancelled:
        raise ValidationError(
            {
                "payment": (
                    "تم إلغاء هذه الدفعة مسبقًا."
                )
            }
        )

    locked_payment.is_cancelled = True
    locked_payment.cancellation_reason = (
        cancellation_reason
    )
    locked_payment.cancelled_by = actor
    locked_payment.cancelled_at = (
        timezone.now()
    )

    locked_payment.save(
        update_fields=[
            "is_cancelled",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
        ]
    )

    return locked_payment