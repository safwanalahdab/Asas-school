from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from accounts.permissions import ActionBusinessPermission
from students.models import Enrollment, GuardianStudent, Student

from .models import GradeTuitionPlan, Payment, StudentDiscount, StudentFinancialAccount


User = get_user_model()


class WebFinancePermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = self.user("admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.user("teacher", User.Role.TEACHER)
        self.guardian = self.user("guardian", User.Role.GUARDIAN)
        self.other_guardian = self.user("other", User.Role.GUARDIAN)
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            status=AcademicYear.Status.ACTIVE,
        )
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Test")
        self.section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="A",
        )
        self.plan = GradeTuitionPlan.objects.create(
            academic_year=self.year, grade_level=self.grade,
            base_tuition_usd=Decimal("1000.00"), created_by=self.admin,
        )
        self.owned = self.account("Owned", self.guardian)
        self.other = self.account("Other", self.other_guardian)

    def user(self, username, role):
        return User.objects.create_user(
            username=username, password="StrongPass!123", role=role,
            must_change_password=False,
        )

    def account(self, name, guardian):
        student = Student.objects.create(
            first_name=name, last_name="Child", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=guardian, student=student)
        enrollment = Enrollment.objects.create(
            student=student, academic_year=self.year, section=self.section,
            enrollment_date=date(2026, 1, 1),
        )
        return StudentFinancialAccount.objects.create(
            enrollment=enrollment, tuition_plan=self.plan, created_by=self.admin,
        )

    def grant(self, user, code):
        app, codename = code.split(".")
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label=app, codename=codename,
        ))

    def login(self, user):
        self.client.force_authenticate(user=user)

    def test_tuition_actions_use_direct_permissions(self):
        list_url = "/api/v1/finance/tuition-plans/"
        detail_url = f"{list_url}{self.plan.pk}/"
        self.login(self.teacher)
        self.assertEqual(self.client.get(list_url).status_code, 403)
        self.grant(self.teacher, "finance.view_gradetuitionplan")
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.assertEqual(self.client.post(list_url, {}).status_code, 403)
        self.assertEqual(self.client.patch(detail_url, {}).status_code, 403)
        self.grant(self.teacher, "finance.change_gradetuitionplan")
        self.assertEqual(self.client.patch(detail_url, {"base_tuition_usd": "1001.00"}).status_code, 200)
        superuser = User.objects.create_superuser(username="root", password="StrongPass!123")
        self.login(superuser)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.put(detail_url, {}).status_code, 405)
        self.assertEqual(self.client.delete(detail_url).status_code, 405)
        self.login(self.admin)
        self.admin.user_permissions.clear()
        self.assertEqual(self.client.get(list_url).status_code, 403)

    def test_account_actions_are_independent_and_role_does_not_limit_scope(self):
        list_url = "/api/v1/finance/accounts/"
        detail_url = f"{list_url}{self.other.pk}/"
        payment_url = f"{detail_url}payments/"
        self.login(self.teacher)
        self.assertEqual(self.client.get(list_url).status_code, 403)
        self.assertEqual(self.client.post(payment_url, {}).status_code, 403)
        self.grant(self.teacher, "finance.view_studentfinancialaccount")
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.grant(self.teacher, "finance.add_payment")
        self.assertEqual(self.client.post(payment_url, {"currency": "usd", "amount": "10.00"}).status_code, 201)
        self.assertEqual(self.client.post(f"{payment_url}missing/cancel/", {}).status_code, 403)
        self.login(self.admin)
        self.admin.user_permissions.clear()
        self.grant(self.admin, "finance.view_studentfinancialaccount")
        self.grant(self.admin, "finance.add_payment")
        self.admin.user_permissions.remove(Permission.objects.get(
            content_type__app_label="finance", codename="add_payment",
        ))
        self.assertEqual(self.client.post(payment_url, {}).status_code, 403)

    def test_supervisor_and_tech_support_with_direct_view_permission(self):
        url = f"/api/v1/finance/accounts/{self.other.pk}/"
        for role in (User.Role.SUPERVISOR, User.Role.TECH_SUPPORT):
            with self.subTest(role=role):
                user = self.user(role, role)
                self.login(user)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.grant(user, "finance.view_studentfinancialaccount")
                self.assertEqual(self.client.get("/api/v1/finance/accounts/").status_code, 200)
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_superuser_bypasses_finance_permissions(self):
        superuser = User.objects.create_superuser(username="finance-root", password="StrongPass!123")
        self.login(superuser)
        list_url = "/api/v1/finance/accounts/"
        detail_url = f"{list_url}{self.other.pk}/"
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.assertEqual(self.client.post(detail_url + "payments/", {
            "currency": "usd", "amount": "10.00",
        }).status_code, 201)

    def test_payment_and_discount_permissions_are_separate(self):
        detail_url = f"/api/v1/finance/accounts/{self.other.pk}/"
        self.login(self.teacher)
        self.grant(self.teacher, "finance.add_payment")
        payment_response = self.client.post(detail_url + "payments/", {
            "currency": "usd", "amount": "10.00",
        })
        self.assertEqual(payment_response.status_code, 201)
        payment = Payment.objects.get(account=self.other)
        cancel_payment_url = f"{detail_url}payments/{payment.pk}/cancel/"
        self.assertEqual(self.client.post(cancel_payment_url, {"cancellation_reason": "Correction"}).status_code, 403)
        self.grant(self.teacher, "finance.cancel_payment")
        self.assertEqual(self.client.post(cancel_payment_url, {"cancellation_reason": "Correction"}).status_code, 200)
        self.assertEqual(self.client.post(detail_url + "discounts/", {}).status_code, 403)
        self.grant(self.teacher, "finance.add_studentdiscount")
        self.assertEqual(self.client.post(detail_url + "discounts/", {
            "discount_type": "percentage", "value": "5.00",
        }).status_code, 201)
        discount = StudentDiscount.objects.get(account=self.other)
        cancel_discount_url = f"{detail_url}discounts/{discount.pk}/cancel/"
        self.assertEqual(self.client.post(cancel_discount_url, {"cancellation_reason": "Correction"}).status_code, 403)
        self.grant(self.teacher, "finance.cancel_discount")
        self.assertEqual(self.client.post(cancel_discount_url, {"cancellation_reason": "Correction"}).status_code, 200)

    def test_guardian_scope_applies_to_reads_and_custom_actions(self):
        list_url = "/api/v1/finance/accounts/"
        own_url = f"{list_url}{self.owned.pk}/"
        other_url = f"{list_url}{self.other.pk}/"
        self.login(self.guardian)
        self.assertEqual(self.client.get(list_url).status_code, 403)
        self.grant(self.guardian, "finance.view_studentfinancialaccount")
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["data"]["results"]],
            [str(self.owned.pk)],
        )
        self.assertEqual(self.client.get(own_url).status_code, 200)
        self.assertEqual(self.client.get(other_url).status_code, 404)
        self.assertEqual(self.client.get(list_url, {"student": self.other.enrollment.student_id}).data["data"]["results"], [])
        self.grant(self.guardian, "finance.add_payment")
        self.assertEqual(self.client.post(f"{other_url}payments/", {"currency": "usd", "amount": "10.00"}).status_code, 404)

    def test_custom_actions_require_their_own_permission(self):
        detail_url = f"/api/v1/finance/accounts/{self.owned.pk}/"
        self.login(self.teacher)
        preview_url = detail_url + "remaining-syp-preview/"
        payload = {"exchange_rate_syp_per_usd": "13000.0000"}
        self.assertEqual(self.client.post(preview_url, payload).status_code, 403)
        self.grant(self.teacher, "finance.view_studentfinancialaccount")
        self.assertEqual(self.client.post(preview_url, payload).status_code, 200)

    def test_reachable_unmapped_action_fails_closed(self):
        permission = ActionBusinessPermission()
        view = SimpleNamespace(
            action="unmapped", action_permissions={}, http_method_names=["get"],
        )
        request = SimpleNamespace(method="GET", user=self.admin)
        self.assertFalse(permission.has_permission(request, view))

    def test_create_plan_requires_add_permission_even_for_admin(self):
        url = "/api/v1/finance/tuition-plans/"
        self.login(self.admin)
        self.admin.user_permissions.clear()
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.grant(self.admin, "finance.add_gradetuitionplan")
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Another")
        response = self.client.post(url, {
            "academic_year": str(self.year.pk),
            "grade_level": str(grade.pk),
            "base_tuition_usd": "500.00",
        })
        self.assertEqual(response.status_code, 201)
