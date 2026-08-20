from decimal import Decimal

from rest_framework import serializers

from .models import (
    GradeTuitionPlan,
    MoneyCurrency,
    Payment,
    StudentDiscount,
    StudentFinancialAccount,
)
from .services import (
    calculate_account_totals,
    calculate_discount_usd,
)


class GradeTuitionPlanSerializer(
    serializers.ModelSerializer
):
    academic_year_display = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source="grade_level.name",
        read_only=True,
    )

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = GradeTuitionPlan

        fields = (
            "id",
            "academic_year",
            "academic_year_display",
            "grade_level",
            "grade_level_display",
            "base_tuition_usd",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        )

    def validate_base_tuition_usd(
        self,
        value,
    ):
        if value <= 0:
            raise serializers.ValidationError(
                "يجب أن يكون سعر الصف أكبر من صفر."
            )

        return value

    def validate(self, attrs):
        if self.instance is not None:
            errors = {}

            if "academic_year" in attrs:
                errors["academic_year"] = (
                    "لا يمكن تغيير السنة الدراسية "
                    "لخطة الرسوم بعد إنشائها."
                )

            if "grade_level" in attrs:
                errors["grade_level"] = (
                    "لا يمكن تغيير الصف "
                    "لخطة الرسوم بعد إنشائها."
                )

            if errors:
                raise serializers.ValidationError(
                    errors
                )

            return attrs

        academic_year = attrs.get(
            "academic_year"
        )

        grade_level = attrs.get(
            "grade_level"
        )

        if (
            academic_year
            and grade_level
            and GradeTuitionPlan.objects.filter(
                academic_year=academic_year,
                grade_level=grade_level,
            ).exists()
        ):
            raise serializers.ValidationError(
                {
                    "grade_level": (
                        "يوجد سعر محدد مسبقًا "
                        "لهذا الصف في هذه السنة."
                    )
                }
            )

        return attrs


class AccountTotalsSerializer(
    serializers.Serializer
):
    base_tuition_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    total_discounts_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    net_tuition_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    total_paid_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    remaining_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    payment_status = serializers.CharField(
        read_only=True,
    )


class StudentDiscountSerializer(
    serializers.ModelSerializer
):
    discount_type_display = serializers.CharField(
        source="get_discount_type_display",
        read_only=True,
    )

    currency_display = serializers.CharField(
        source="get_currency_display",
        read_only=True,
    )

    discount_usd = (
        serializers.SerializerMethodField()
    )

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    cancelled_by_username = serializers.CharField(
        source="cancelled_by.username",
        read_only=True,
    )

    class Meta:
        model = StudentDiscount

        fields = (
            "id",
            "discount_type",
            "discount_type_display",
            "value",
            "currency",
            "currency_display",
            "exchange_rate_syp_per_usd",
            "equivalent_usd",
            "discount_usd",
            "reason",
            "is_cancelled",
            "cancellation_reason",
            "created_by",
            "created_by_username",
            "cancelled_by",
            "cancelled_by_username",
            "cancelled_at",
            "created_at",
        )

        read_only_fields = fields

    def get_discount_usd(
        self,
        obj,
    ):
        value = calculate_discount_usd(
            obj,
            base_tuition_usd=(
                obj.account
                .tuition_plan
                .base_tuition_usd
            ),
        )

        return format(
            value,
            ".2f",
        )


class PaymentSerializer(
    serializers.ModelSerializer
):
    currency_display = serializers.CharField(
        source="get_currency_display",
        read_only=True,
    )

    recorded_by_username = serializers.CharField(
        source="recorded_by.username",
        read_only=True,
    )

    cancelled_by_username = serializers.CharField(
        source="cancelled_by.username",
        read_only=True,
    )

    class Meta:
        model = Payment

        fields = (
            "id",
            "currency",
            "currency_display",
            "amount",
            "exchange_rate_syp_per_usd",
            "equivalent_usd",
            "paid_at",
            "recorded_by",
            "recorded_by_username",
            "is_cancelled",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_by_username",
            "cancelled_at",
            "created_at",
        )

        read_only_fields = fields


class StudentFinancialAccountListSerializer(
    serializers.ModelSerializer
):
    student = serializers.UUIDField(
        source="enrollment.student_id",
        read_only=True,
    )

    student_display = serializers.CharField(
        source="enrollment.student.full_name",
        read_only=True,
    )

    academic_year = serializers.UUIDField(
        source="enrollment.academic_year_id",
        read_only=True,
    )

    academic_year_display = serializers.CharField(
        source="enrollment.academic_year.name",
        read_only=True,
    )

    grade_level = serializers.UUIDField(
        source=(
            "enrollment.section.grade_level_id"
        ),
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source=(
            "enrollment.section.grade_level.name"
        ),
        read_only=True,
    )

    base_tuition_usd = serializers.DecimalField(
        source="tuition_plan.base_tuition_usd",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    totals = serializers.SerializerMethodField()

    class Meta:
        model = StudentFinancialAccount

        fields = (
            "id",
            "enrollment",
            "student",
            "student_display",
            "academic_year",
            "academic_year_display",
            "grade_level",
            "grade_level_display",
            "tuition_plan",
            "base_tuition_usd",
            "totals",
            "created_at",
        )

        read_only_fields = fields

    def get_totals(
        self,
        obj,
    ):
        totals = calculate_account_totals(
            obj
        )

        if totals["remaining_usd"] <= 0:
            payment_status = "paid"

        elif totals["total_paid_usd"] > 0:
            payment_status = "partial"

        else:
            payment_status = "unpaid"

        totals["payment_status"] = (
            payment_status
        )

        return AccountTotalsSerializer(
            totals
        ).data


class StudentFinancialAccountDetailSerializer(
    StudentFinancialAccountListSerializer
):
    discounts = StudentDiscountSerializer(
        many=True,
        read_only=True,
    )

    payments = PaymentSerializer(
        many=True,
        read_only=True,
    )

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta(
        StudentFinancialAccountListSerializer.Meta
    ):
        fields = (
            *StudentFinancialAccountListSerializer
            .Meta.fields,
            "discounts",
            "payments",
            "created_by",
            "created_by_username",
            "updated_at",
        )


class AddDiscountSerializer(
    serializers.Serializer
):
    discount_type = serializers.ChoiceField(
        choices=(
            StudentDiscount
            .DiscountType
            .choices
        ),
    )

    value = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    currency = serializers.ChoiceField(
        choices=MoneyCurrency.choices,
        required=False,
        allow_blank=True,
        default="",
    )

    exchange_rate_syp_per_usd = (
        serializers.DecimalField(
            max_digits=18,
            decimal_places=4,
            required=False,
            allow_null=True,
            min_value=Decimal("0.0001"),
        )
    )

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class RecordPaymentSerializer(
    serializers.Serializer
):
    currency = serializers.ChoiceField(
        choices=MoneyCurrency.choices,
    )

    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    exchange_rate_syp_per_usd = (
        serializers.DecimalField(
            max_digits=18,
            decimal_places=4,
            required=False,
            allow_null=True,
            min_value=Decimal("0.0001"),
        )
    )


class CancelFinancialRecordSerializer(
    serializers.Serializer
):
    cancellation_reason = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )


class RemainingSypPreviewSerializer(
    serializers.Serializer
):
    exchange_rate_syp_per_usd = (
        serializers.DecimalField(
            max_digits=18,
            decimal_places=4,
            min_value=Decimal("0.0001"),
        )
    )


class RemainingSypPreviewResultSerializer(
    serializers.Serializer
):
    remaining_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    exchange_rate_syp_per_usd = (
        serializers.DecimalField(
            max_digits=18,
            decimal_places=4,
            read_only=True,
        )
    )

    remaining_syp = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        read_only=True,
    )