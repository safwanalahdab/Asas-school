import uuid
from datetime import date, timedelta

from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from accounts.services import delete_guardian_account
from appointments.models import AppointmentRequest
from audit_logs.models import AuditLog
from notifications.models import Notification, PushDevice
from notifications.services import create_notification
from school_requests.models import SchoolRequest
from students.models import (
    GuardianStudent,
    Student,
    StudentImportJob,
    StudentImportRow,
)
from students.services import register_student


class GuardianAccountDeletionTests(TestCase):
    url = "/api/v1/auth/mobile/delete-account/"
    login_url = "/api/v1/auth/mobile/login/"
    refresh_url = "/api/v1/auth/mobile/refresh/"
    me_url = "/api/v1/auth/mobile/me/"
    password = "DeleteMe!934"
    national_id = "123456789012"
    personal_values = (
        "123456789012", "Ahmad", "Khaled", "ahmad.khaled@example.com",
        "0933111222",
    )

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.guardian = User.objects.create_user(
            username=self.national_id,
            national_id=self.national_id,
            email="ahmad.khaled@example.com",
            phone_number="0933111222",
            first_name="Ahmad",
            last_name="Khaled",
            password=self.password,
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.guardian.user_permissions.add(Permission.objects.first())
        self.guardian.groups.add(Group.objects.create(name="deletion-test-group"))
        self.staff = User.objects.create_user(
            username="deletion-staff",
            password=self.password,
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.other_guardian = User.objects.create_user(
            username="other-guardian",
            password=self.password,
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

        self.student = Student.objects.create(
            first_name="Sami",
            last_name="Khaled",
            father_name="Ahmad",
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        self.link = GuardianStudent.objects.create(
            guardian=self.guardian, student=self.student, relationship="أب",
        )
        self.devices = [self.make_device(self.guardian) for _ in range(2)]
        self.other_device = self.make_device(self.other_guardian)
        create_notification(
            recipient=self.guardian,
            notification_type=Notification.NotificationType.GENERAL,
            title="Title",
            body="Body",
        )
        self.school_request = SchoolRequest.objects.create(
            request_type=SchoolRequest.RequestType.INQUIRY,
            details="استفسار من ولي الأمر",
            guardian=self.guardian,
            student=self.student,
        )
        self.appointment = AppointmentRequest.objects.create(
            guardian=self.guardian,
            requested_date=date(2026, 11, 1),
            request_reason="سبب الموعد",
        )
        job = StudentImportJob.objects.create(
            created_by=self.staff,
            original_filename="students.xlsx",
            file_sha256="0" * 64,
            file_size=1,
        )
        self.import_row = StudentImportRow.objects.create(
            job=job,
            row_number=1,
            status=StudentImportRow.Status.SUCCEEDED,
            student=self.student,
            guardian=self.guardian,
            normalized_data={
                "student": {"first_name": "Sami"},
                "guardian": {"national_id": self.national_id, "first_name": "Ahmad"},
            },
        )
        self.other_import_row = StudentImportRow.objects.create(
            job=job,
            row_number=2,
            normalized_data={"guardian": {"national_id": "999999999999"}},
        )

    def make_device(self, user):
        return PushDevice.objects.create(
            user=user,
            installation_id=uuid.uuid4(),
            fcm_token=f"token-{uuid.uuid4()}",
            platform=PushDevice.Platform.ANDROID,
            last_seen_at=timezone.now(),
        )

    def token_pair(self, user=None, client="mobile"):
        user = user or self.guardian
        refresh = RefreshToken.for_user(user)
        refresh["client"] = client
        refresh["token_version"] = user.token_version
        return str(refresh.access_token), str(refresh)

    def login(self, identifier, password=None):
        return self.client.post(
            self.login_url,
            {"identifier": identifier, "password": password or self.password},
            format="json",
        )

    def delete_account(self, password=None, access=None):
        if access is None:
            access, _ = self.token_pair()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.post(
            self.url, {"password": password or self.password}, format="json"
        )
        self.client.credentials()
        return response

    def snapshot(self):
        self.guardian.refresh_from_db()
        return {
            "guardian": (
                self.guardian.username, self.guardian.email,
                self.guardian.national_id, self.guardian.is_active,
                self.guardian.password, self.guardian.token_version,
            ),
            "devices": PushDevice.objects.filter(user=self.guardian).count(),
            "notifications": Notification.objects.filter(
                recipient=self.guardian
            ).count(),
            "link_active": GuardianStudent.objects.get(pk=self.link.pk).is_active,
            "import_row": StudentImportRow.objects.get(
                pk=self.import_row.pk
            ).normalized_data,
        }

    def test_guardian_with_correct_password_deletes_account(self):
        response = self.delete_account()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["code"], "ACCOUNT_DELETED")
        self.assertEqual(response.data["message"], "تم حذف الحساب بنجاح.")
        self.guardian.refresh_from_db()
        self.assertFalse(self.guardian.is_active)
        self.assertFalse(self.guardian.has_usable_password())
        self.assertRegex(
            self.guardian.username,
            r"^deleted-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )
        self.assertEqual(self.guardian.first_name, "")
        self.assertEqual(self.guardian.last_name, "")
        self.assertIsNone(self.guardian.email)
        self.assertEqual(self.guardian.phone_number, "")
        self.assertIsNone(self.guardian.national_id)
        self.assertFalse(self.guardian.must_change_password)
        self.assertIsNone(self.guardian.temporary_password_expires_at)
        self.assertFalse(self.guardian.user_permissions.exists())
        self.assertFalse(self.guardian.groups.exists())
        self.assertEqual(self.guardian.role, User.Role.GUARDIAN)

    def test_old_tokens_and_credentials_stop_working(self):
        login = self.login(self.national_id)
        self.assertEqual(login.status_code, 200)
        access, refresh = login.data["data"]["access"], login.data["data"]["refresh"]
        _, second_refresh = self.token_pair()

        self.assertEqual(self.delete_account(access=access).status_code, 200)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get(self.me_url).status_code, 401)
        self.client.credentials()
        for token in (refresh, second_refresh):
            response = self.client.post(
                self.refresh_url, {"refresh": token}, format="json"
            )
            self.assertEqual(response.status_code, 401)
        outstanding = OutstandingToken.objects.filter(user=self.guardian)
        self.assertTrue(outstanding.exists())
        self.assertFalse(outstanding.filter(blacklistedtoken__isnull=True).exists())
        for identifier in (self.national_id, "ahmad.khaled@example.com"):
            cache.clear()
            self.assertEqual(self.login(identifier).status_code, 401)

    def test_wrong_password_returns_400_and_changes_nothing(self):
        before = self.snapshot()

        response = self.delete_account(password="Wrong!934")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertEqual(
            response.data["errors"]["password"], ["كلمة المرور الحالية غير صحيحة."]
        )
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(
            AuditLog.objects.filter(action=AuditLog.Action.DELETE).exists()
        )

    def test_missing_password_returns_400(self):
        access, _ = self.token_pair()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data["errors"])

    def test_unauthenticated_request_returns_401(self):
        response = self.client.post(
            self.url, {"password": self.password}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.guardian.refresh_from_db()
        self.assertTrue(self.guardian.is_active)

    def test_web_tokens_and_staff_are_rejected(self):
        before = self.snapshot()
        staff_web, _ = self.token_pair(self.staff, client="web")
        guardian_web, _ = self.token_pair(client="web")
        staff_mobile, _ = self.token_pair(self.staff)
        for name, access, expected in (
            ("staff web token", staff_web, 401),
            ("guardian web token", guardian_web, 401),
            ("staff mobile token", staff_mobile, 403),
        ):
            with self.subTest(name):
                cache.clear()
                response = self.delete_account(access=access)
                self.assertEqual(response.status_code, expected)
        self.assertEqual(self.snapshot(), before)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)
        self.assertEqual(self.staff.username, "deletion-staff")

    def test_forced_password_change_does_not_block_deletion(self):
        self.guardian.must_change_password = True
        self.guardian.temporary_password_expires_at = (
            timezone.now() + timedelta(days=1)
        )
        self.guardian.save(
            update_fields=["must_change_password", "temporary_password_expires_at"]
        )
        response = self.delete_account()
        self.assertEqual(response.status_code, 200, response.data)
        self.guardian.refresh_from_db()
        self.assertFalse(self.guardian.is_active)

    def test_devices_and_notifications_are_removed(self):
        self.assertEqual(self.delete_account().status_code, 200)

        self.assertFalse(PushDevice.objects.filter(user=self.guardian).exists())
        self.assertFalse(
            Notification.objects.filter(recipient=self.guardian).exists()
        )
        self.assertTrue(PushDevice.objects.filter(pk=self.other_device.pk).exists())
        self.guardian.refresh_from_db()
        with self.assertRaises(ValidationError):
            create_notification(
                recipient=self.guardian,
                notification_type=Notification.NotificationType.GENERAL,
                title="After deletion",
                body="Body",
            )

    def test_link_is_deactivated_and_school_records_are_kept(self):
        student_before = Student.objects.filter(pk=self.student.pk).values().get()
        request_before = SchoolRequest.objects.filter(
            pk=self.school_request.pk
        ).values().get()
        appointment_before = AppointmentRequest.objects.filter(
            pk=self.appointment.pk
        ).values().get()
        other_row_before = StudentImportRow.objects.get(
            pk=self.other_import_row.pk
        ).normalized_data

        self.assertEqual(self.delete_account().status_code, 200)

        link = GuardianStudent.objects.get(pk=self.link.pk)
        self.assertFalse(link.is_active)
        self.assertEqual(link.guardian_id, self.guardian.pk)
        self.assertEqual(link.student_id, self.student.pk)
        self.assertEqual(
            Student.objects.filter(pk=self.student.pk).values().get(), student_before
        )
        self.assertEqual(
            SchoolRequest.objects.filter(pk=self.school_request.pk).values().get(),
            request_before,
        )
        self.assertEqual(
            AppointmentRequest.objects.filter(pk=self.appointment.pk).values().get(),
            appointment_before,
        )
        row = StudentImportRow.objects.get(pk=self.import_row.pk)
        self.assertEqual(row.normalized_data, {"student": {"first_name": "Sami"}})
        self.assertEqual(row.guardian_id, self.guardian.pk)
        self.assertEqual(row.student_id, self.student.pk)
        self.assertEqual(
            StudentImportRow.objects.get(pk=self.other_import_row.pk).normalized_data,
            other_row_before,
        )

    def test_national_id_can_register_a_new_guardian(self):
        self.assertEqual(self.delete_account().status_code, 200)

        result = register_student(
            student_data={
                "first_name": "Rami",
                "last_name": "Khaled",
                "birth_date": date(2016, 1, 1),
                "gender": Student.Gender.MALE,
            },
            guardian_data={
                "national_id": self.national_id,
                "first_name": "Ahmad",
                "last_name": "Khaled",
                "relationship": "أب",
            },
        )

        self.assertEqual(result["guardian_account"]["status"], "created")
        new_guardian = User.objects.get(national_id=self.national_id)
        self.assertNotEqual(new_guardian.pk, self.guardian.pk)
        self.assertEqual(new_guardian.username, self.national_id)
        self.assertTrue(new_guardian.is_active)

    def test_audit_entry_has_the_id_only(self):
        self.assertEqual(self.delete_account().status_code, 200)

        entry = AuditLog.objects.get(
            module=AuditLog.Module.ACCOUNTS,
            action=AuditLog.Action.DELETE,
            target_id=str(self.guardian.pk),
        )
        self.assertEqual(entry.actor_id, self.guardian.pk)
        self.assertEqual(entry.target_type, "accounts.User")
        self.assertEqual(entry.target_display, str(self.guardian.pk))
        recorded = " ".join(
            [entry.actor_display, entry.message, entry.target_display, str(entry.metadata)]
        )
        for value in self.personal_values:
            self.assertNotIn(value, recorded)

    def test_deletion_is_throttled(self):
        access, _ = self.token_pair()
        for _ in range(5):
            response = self.delete_account(password="Wrong!934", access=access)
            self.assertEqual(response.status_code, 400)
        response = self.delete_account(access=access)
        self.assertEqual(response.status_code, 429)
        self.guardian.refresh_from_db()
        self.assertTrue(self.guardian.is_active)

    def test_service_rejects_non_guardian_accounts(self):
        with self.assertRaises(ValueError):
            delete_guardian_account(self.staff)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)
        self.assertEqual(self.staff.username, "deletion-staff")
