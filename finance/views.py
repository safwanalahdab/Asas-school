from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import extend_schema

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import (
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import (
    GenericViewSet,
    ModelViewSet,
)

from accounts.permissions import PasswordChangeGate
from config.api_responses import ArabicApiResponseMixin

from .filters import (
    GradeTuitionPlanFilter,
    StudentFinancialAccountFilter,
)
from .models import (
    GradeTuitionPlan,
    Payment,
    StudentDiscount,
    StudentFinancialAccount,
)
from .permissions import (
    CanAccessFinancialAccounts,
    CanManageTuitionPlans,
)
from .serializers import (
    AddDiscountSerializer,
    CancelFinancialRecordSerializer,
    GradeTuitionPlanSerializer,
    PaymentSerializer,
    RecordPaymentSerializer,
    RemainingSypPreviewResultSerializer,
    RemainingSypPreviewSerializer,
    StudentDiscountSerializer,
    StudentFinancialAccountDetailSerializer,
    StudentFinancialAccountListSerializer,
)
from .services import (
    calculate_account_totals,
    cancel_payment as cancel_payment_service,
    cancel_student_discount,
    create_missing_financial_accounts_for_plan,
    create_student_discount,
    record_payment as record_payment_service,
    update_tuition_plan_price,
)
from .utils import convert_usd_to_syp


User = get_user_model()


class GradeTuitionPlanViewSet(
    ArabicApiResponseMixin,
    ModelViewSet,
):
    queryset = (
        GradeTuitionPlan.objects
        .select_related(
            "academic_year",
            "grade_level",
            "created_by",
        )
    )

    serializer_class = GradeTuitionPlanSerializer

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        CanManageTuitionPlans,
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
    ]

    filterset_class = GradeTuitionPlanFilter

    ordering_fields = [
        "base_tuition_usd",
        "created_at",
        "updated_at",
        "academic_year__start_date",
        "grade_level__name",
    ]

    ordering = [
        "-academic_year__start_date",
        "grade_level__name",
    ]

    response_messages = {
        "list": (
            "TUITION_PLANS_RETRIEVED",
            "تم جلب أسعار الرسوم المدرسية بنجاح.",
        ),
        "retrieve": (
            "TUITION_PLAN_RETRIEVED",
            "تم جلب سعر الرسوم بنجاح.",
        ),
        "create": (
            "TUITION_PLAN_CREATED",
            "تمت إضافة سعر الرسوم بنجاح.",
        ),
        "partial_update": (
            "TUITION_PLAN_UPDATED",
            "تم تحديث سعر الرسوم بنجاح.",
        ),
    }

    @transaction.atomic
    def perform_create(
        self,
        serializer,
    ):
        tuition_plan = serializer.save(
            created_by=self.request.user,
        )

        create_missing_financial_accounts_for_plan(
            tuition_plan=tuition_plan,
            actor=self.request.user,
        )

    def perform_update(
        self,
        serializer,
    ):
        new_price = serializer.validated_data.get(
            "base_tuition_usd",
        )

        if new_price is None:
            return

        updated_plan = update_tuition_plan_price(
            tuition_plan=serializer.instance,
            new_base_tuition_usd=new_price,
        )

        serializer.instance = updated_plan


class StudentFinancialAccountViewSet(
    ArabicApiResponseMixin,
    ListModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    queryset = (
        StudentFinancialAccount.objects
        .select_related(
            "enrollment",
            "enrollment__student",
            "enrollment__academic_year",
            "enrollment__section",
            "enrollment__section__grade_level",
            "tuition_plan",
            "tuition_plan__academic_year",
            "tuition_plan__grade_level",
            "created_by",
        )
        .prefetch_related(
            "discounts__created_by",
            "discounts__cancelled_by",
            "payments__recorded_by",
            "payments__cancelled_by",
        )
    )

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        CanAccessFinancialAccounts,
    ]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    filterset_class = StudentFinancialAccountFilter

    ordering_fields = [
        "created_at",
        "updated_at",
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__enrollment_date",
        "enrollment__academic_year__start_date",
        "enrollment__section__grade_level__name",
        "tuition_plan__base_tuition_usd",
    ]

    ordering = [
        "enrollment__student__first_name",
        "enrollment__student__last_name",
    ]

    response_messages = {
        "list": (
            "FINANCIAL_ACCOUNTS_RETRIEVED",
            "تم جلب الحسابات المالية بنجاح.",
        ),
        "retrieve": (
            "FINANCIAL_ACCOUNT_RETRIEVED",
            "تم جلب الحساب المالي بنجاح.",
        ),
        "add_discount": (
            "DISCOUNT_ADDED",
            "تمت إضافة الخصم بنجاح.",
        ),
        "cancel_discount": (
            "DISCOUNT_CANCELLED",
            "تم إلغاء الخصم بنجاح.",
        ),
        "record_payment": (
            "PAYMENT_RECORDED",
            "تم تسجيل الدفعة بنجاح.",
        ),
        "cancel_payment": (
            "PAYMENT_CANCELLED",
            "تم إلغاء الدفعة بنجاح.",
        ),
        "remaining_syp_preview": (
            "REMAINING_SYP_PREVIEWED",
            "تم حساب المبلغ المتبقي بالليرة السورية بنجاح.",
        ),
    }

    def get_serializer_class(self):
        if self.action == "list":
            return StudentFinancialAccountListSerializer

        if self.action == "retrieve":
            return StudentFinancialAccountDetailSerializer

        if self.action == "add_discount":
            return AddDiscountSerializer

        if self.action == "cancel_discount":
            return CancelFinancialRecordSerializer

        if self.action == "record_payment":
            return RecordPaymentSerializer

        if self.action == "cancel_payment":
            return CancelFinancialRecordSerializer

        if self.action == "remaining_syp_preview":
            return RemainingSypPreviewSerializer

        return StudentFinancialAccountDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
        }:
            return queryset

        if user.role == User.Role.GUARDIAN:
            return queryset.filter(
                enrollment__student__guardian_link__guardian=user,
                enrollment__student__guardian_link__is_active=True,
                enrollment__student__is_active=True,
            )

        return queryset.none()

    @extend_schema(
        request=AddDiscountSerializer,
        responses={
            201: StudentDiscountSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="discounts",
    )
    def add_discount(
        self,
        request,
        pk=None,
    ):
        account = self.get_object()

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        discount = create_student_discount(
            account=account,
            discount_type=serializer.validated_data[
                "discount_type"
            ],
            value=serializer.validated_data[
                "value"
            ],
            currency=serializer.validated_data.get(
                "currency",
                "",
            ),
            exchange_rate_syp_per_usd=(
                serializer.validated_data.get(
                    "exchange_rate_syp_per_usd",
                )
            ),
            reason=serializer.validated_data.get(
                "reason",
                "",
            ),
            actor=request.user,
        )

        response_serializer = StudentDiscountSerializer(
            discount,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=CancelFinancialRecordSerializer,
        responses={
            200: StudentDiscountSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=(
            r"discounts/"
            r"(?P<discount_id>[^/.]+)/cancel"
        ),
    )
    def cancel_discount(
        self,
        request,
        pk=None,
        discount_id=None,
    ):
        account = self.get_object()

        discount = get_object_or_404(
            StudentDiscount.objects.filter(
                account=account,
            ),
            pk=discount_id,
        )

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        discount = cancel_student_discount(
            discount=discount,
            actor=request.user,
            cancellation_reason=(
                serializer.validated_data[
                    "cancellation_reason"
                ]
            ),
        )

        response_serializer = StudentDiscountSerializer(
            discount,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=RecordPaymentSerializer,
        responses={
            201: PaymentSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="payments",
    )
    def record_payment(
        self,
        request,
        pk=None,
    ):
        account = self.get_object()

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        payment = record_payment_service(
            account=account,
            currency=serializer.validated_data[
                "currency"
            ],
            amount=serializer.validated_data[
                "amount"
            ],
            exchange_rate_syp_per_usd=(
                serializer.validated_data.get(
                    "exchange_rate_syp_per_usd",
                )
            ),
            actor=request.user,
        )

        response_serializer = PaymentSerializer(
            payment,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=CancelFinancialRecordSerializer,
        responses={
            200: PaymentSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=(
            r"payments/"
            r"(?P<payment_id>[^/.]+)/cancel"
        ),
    )
    def cancel_payment(
        self,
        request,
        pk=None,
        payment_id=None,
    ):
        account = self.get_object()

        payment = get_object_or_404(
            Payment.objects.filter(
                account=account,
            ),
            pk=payment_id,
        )

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        payment = cancel_payment_service(
            payment=payment,
            actor=request.user,
            cancellation_reason=(
                serializer.validated_data[
                    "cancellation_reason"
                ]
            ),
        )

        response_serializer = PaymentSerializer(
            payment,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=RemainingSypPreviewSerializer,
        responses={
            200: RemainingSypPreviewResultSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="remaining-syp-preview",
    )
    def remaining_syp_preview(
        self,
        request,
        pk=None,
    ):
        account = self.get_object()

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        exchange_rate = serializer.validated_data[
            "exchange_rate_syp_per_usd"
        ]

        totals = calculate_account_totals(
            account
        )

        remaining_usd = totals[
            "remaining_usd"
        ]

        remaining_syp = convert_usd_to_syp(
            remaining_usd,
            exchange_rate,
        )

        result = {
            "remaining_usd": remaining_usd,
            "exchange_rate_syp_per_usd": exchange_rate,
            "remaining_syp": remaining_syp,
        }

        response_serializer = (
            RemainingSypPreviewResultSerializer(
                result
            )
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )