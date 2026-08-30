from rest_framework import serializers

from .models import Payment


class MobileFinanceStudentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()


class MobileFinanceAcademicYearSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MobileFinanceSummarySerializer(serializers.Serializer):
    currency = serializers.CharField()
    base_tuition_usd = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_discounts_usd = serializers.DecimalField(max_digits=12, decimal_places=2)
    net_tuition_usd = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_paid_usd = serializers.DecimalField(max_digits=12, decimal_places=2)
    remaining_usd = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_status = serializers.ChoiceField(choices=("paid", "partial", "unpaid"))


class MobileDiscountSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    discount_type = serializers.CharField()
    discount_type_display = serializers.CharField()
    value = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(allow_blank=True)
    currency_display = serializers.CharField(allow_blank=True)
    exchange_rate_syp_per_usd = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True
    )
    equivalent_usd = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    discount_usd = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(allow_blank=True)
    is_cancelled = serializers.BooleanField()


class MobilePaymentSerializer(serializers.ModelSerializer):
    currency_display = serializers.CharField(source="get_currency_display")

    class Meta:
        model = Payment
        fields = (
            "id", "currency", "currency_display", "amount",
            "exchange_rate_syp_per_usd", "equivalent_usd", "paid_at",
            "is_cancelled",
        )
        read_only_fields = fields


class MobileFinanceDataSerializer(serializers.Serializer):
    student = MobileFinanceStudentSerializer()
    academic_year = MobileFinanceAcademicYearSerializer(allow_null=True)
    account_configured = serializers.BooleanField()
    summary = MobileFinanceSummarySerializer(allow_null=True)
    discounts = MobileDiscountSerializer(many=True)
    payments = MobilePaymentSerializer(many=True)


class MobileFinanceMetaSerializer(serializers.Serializer):
    requester_role = serializers.JSONField(allow_null=True)


class MobileFinanceResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="MOBILE_CHILD_FINANCE_RETRIEVED")
    message = serializers.CharField()
    data = MobileFinanceDataSerializer()
    meta = MobileFinanceMetaSerializer()


class MobileFinanceErrorSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    code = serializers.CharField()
    message = serializers.CharField()
    errors = serializers.JSONField(required=False)
    meta = MobileFinanceMetaSerializer()
