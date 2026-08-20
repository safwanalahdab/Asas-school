from django.contrib import admin

from .models import (
    GradeTuitionPlan,
    Payment,
    StudentDiscount,
    StudentFinancialAccount,
)
from .services import (
    create_missing_financial_accounts_for_plan,
)


class SuperuserFullAccessAdminMixin:
    """
    السوبر يوزر لديه صلاحيات الإضافة والتعديل والحذف.

    المستخدمون الآخرون لا يستطيعون تعديل السجلات
    من Django Admin.
    """

    superuser_readonly_fields = ()

    def has_add_permission(
        self,
        request,
    ):
        return request.user.is_superuser

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        return request.user.is_superuser

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return request.user.is_superuser

    def get_readonly_fields(
        self,
        request,
        obj=None,
    ):
        if request.user.is_superuser:
            return self.superuser_readonly_fields

        return self.readonly_fields


@admin.register(GradeTuitionPlan)
class GradeTuitionPlanAdmin(
    SuperuserFullAccessAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "academic_year",
        "grade_level",
        "base_tuition_usd",
        "created_by",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "academic_year",
        "grade_level",
    )

    search_fields = (
        "grade_level__name",
        "created_by__username",
        "created_by__first_name",
        "created_by__last_name",
    )

    list_select_related = (
        "academic_year",
        "grade_level",
        "created_by",
    )

    readonly_fields = (
        "id",
        "academic_year",
        "grade_level",
        "base_tuition_usd",
        "created_by",
        "created_at",
        "updated_at",
    )

    superuser_readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):
        super().save_model(
            request,
            obj,
            form,
            change,
        )

        if not change:
            create_missing_financial_accounts_for_plan(
                tuition_plan=obj,
                actor=request.user,
            )


@admin.register(StudentFinancialAccount)
class StudentFinancialAccountAdmin(
    SuperuserFullAccessAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "student_display",
        "academic_year_display",
        "grade_level_display",
        "base_tuition_display",
        "created_by",
        "created_at",
    )

    list_filter = (
        "enrollment__academic_year",
        "enrollment__section__grade_level",
    )

    search_fields = (
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__student__father_name",
        "created_by__username",
    )

    list_select_related = (
        "enrollment",
        "enrollment__student",
        "enrollment__academic_year",
        "enrollment__section",
        "enrollment__section__grade_level",
        "tuition_plan",
        "created_by",
    )

    readonly_fields = (
        "id",
        "enrollment",
        "tuition_plan",
        "created_by",
        "created_at",
        "updated_at",
    )

    superuser_readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    @admin.display(
        description="الطالب",
        ordering="enrollment__student__first_name",
    )
    def student_display(self, obj):
        return obj.enrollment.student.full_name

    @admin.display(
        description="السنة الدراسية",
        ordering="enrollment__academic_year__start_date",
    )
    def academic_year_display(self, obj):
        return obj.enrollment.academic_year.name

    @admin.display(
        description="الصف",
        ordering="enrollment__section__grade_level__name",
    )
    def grade_level_display(self, obj):
        return (
            obj.enrollment
            .section
            .grade_level
            .name
        )

    @admin.display(
        description="القسط الأساسي",
        ordering="tuition_plan__base_tuition_usd",
    )
    def base_tuition_display(self, obj):
        return (
            f"{obj.tuition_plan.base_tuition_usd} USD"
        )


@admin.register(StudentDiscount)
class StudentDiscountAdmin(
    SuperuserFullAccessAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "student_display",
        "discount_type",
        "value",
        "currency",
        "equivalent_usd",
        "is_cancelled",
        "created_by",
        "created_at",
    )

    list_filter = (
        "discount_type",
        "currency",
        "is_cancelled",
        "account__enrollment__academic_year",
    )

    search_fields = (
        "account__enrollment__student__first_name",
        "account__enrollment__student__last_name",
        "account__enrollment__student__father_name",
        "reason",
        "created_by__username",
    )

    list_select_related = (
        "account",
        "account__enrollment",
        "account__enrollment__student",
        "created_by",
        "cancelled_by",
    )

    readonly_fields = (
        "id",
        "account",
        "discount_type",
        "value",
        "currency",
        "exchange_rate_syp_per_usd",
        "equivalent_usd",
        "reason",
        "created_by",
        "is_cancelled",
        "cancellation_reason",
        "cancelled_by",
        "cancelled_at",
        "created_at",
    )

    superuser_readonly_fields = (
        "id",
        "created_at",
    )

    @admin.display(
        description="الطالب",
        ordering="account__enrollment__student__first_name",
    )
    def student_display(self, obj):
        return (
            obj.account
            .enrollment
            .student
            .full_name
        )


@admin.register(Payment)
class PaymentAdmin(
    SuperuserFullAccessAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "student_display",
        "amount",
        "currency",
        "equivalent_usd",
        "paid_at",
        "is_cancelled",
        "recorded_by",
    )

    list_filter = (
        "currency",
        "is_cancelled",
        "paid_at",
        "account__enrollment__academic_year",
    )

    search_fields = (
        "account__enrollment__student__first_name",
        "account__enrollment__student__last_name",
        "account__enrollment__student__father_name",
        "recorded_by__username",
    )

    list_select_related = (
        "account",
        "account__enrollment",
        "account__enrollment__student",
        "recorded_by",
        "cancelled_by",
    )

    readonly_fields = (
        "id",
        "account",
        "currency",
        "amount",
        "exchange_rate_syp_per_usd",
        "equivalent_usd",
        "paid_at",
        "recorded_by",
        "is_cancelled",
        "cancellation_reason",
        "cancelled_by",
        "cancelled_at",
        "created_at",
    )

    superuser_readonly_fields = (
        "id",
        "created_at",
    )

    @admin.display(
        description="الطالب",
        ordering="account__enrollment__student__first_name",
    )
    def student_display(self, obj):
        return (
            obj.account
            .enrollment
            .student
            .full_name
        )