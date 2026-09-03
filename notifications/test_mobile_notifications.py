import uuid
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from notifications.models import Notification
from students.models import GuardianStudent, Student


User = get_user_model()


class MobileNotificationApiTests(TestCase):
    list_url = "/api/v1/mobile/notifications/"

    def setUp(self):
        self.client = APIClient()
        self.guardian = self.make_guardian("notification-guardian")
        self.other_guardian = self.make_guardian("notification-other")
        self.student = Student.objects.create(
            first_name="أحمد",
            last_name="خالد",
            birth_date=date(2018, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.student,
        )
        self.resource_id = uuid.uuid4()
        self.older = self.make_notification(title="Older")
        self.newer = self.make_notification(
            title="Newer",
            notification_type=Notification.NotificationType.HOMEWORK,
            student=self.student,
            resource_type="homework",
            resource_id=self.resource_id,
        )
        now = timezone.now()
        Notification.objects.filter(pk=self.older.pk).update(
            created_at=now - timedelta(days=1)
        )
        Notification.objects.filter(pk=self.newer.pk).update(created_at=now)
        self.other = self.make_notification(
            recipient=self.other_guardian,
            title="Other",
        )

    def make_guardian(self, username, **overrides):
        values = {
            "username": username,
            "password": "StrongPass!493",
            "role": User.Role.GUARDIAN,
            "must_change_password": False,
        }
        values.update(overrides)
        return User.objects.create_user(**values)

    def make_notification(self, **overrides):
        values = {
            "recipient": self.guardian,
            "notification_type": Notification.NotificationType.GENERAL,
            "title": "Notification",
            "body": "Notification body",
        }
        values.update(overrides)
        return Notification.objects.create(**values)

    def authenticate(self, *, user=None, client="mobile", api_client=None):
        user = user or self.guardian
        api_client = api_client or self.client
        token = RefreshToken.for_user(user)
        token["client"] = client
        token["token_version"] = user.token_version
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def detail_url(self, notification):
        return f"{self.list_url}{notification.id}/"

    def test_list_is_scoped_ordered_and_has_expected_contract(self):
        self.authenticate()
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        results = response.data["data"]["results"]
        self.assertEqual(
            [item["id"] for item in results],
            [str(self.newer.id), str(self.older.id)],
        )
        item = results[0]
        self.assertEqual(
            set(item),
            {
                "id", "type", "type_display", "title", "body", "is_read",
                "read_at", "created_at", "student", "resource_type",
                "resource_id", "data",
            },
        )
        self.assertEqual(item["type"], "homework")
        self.assertEqual(
            item["type_display"],
            Notification.NotificationType.HOMEWORK.label,
        )
        self.assertEqual(
            item["student"],
            {"id": str(self.student.id), "full_name": self.student.full_name},
        )
        self.assertEqual(
            item["data"],
            {
                "student_id": str(self.student.id),
                "resource_type": "homework",
                "resource_id": str(self.resource_id),
            },
        )
        self.assertNotIn(str(self.other.id), {item["id"] for item in results})
        forbidden = {"recipient", "recipient_id", "updated_at", "event_key"}
        self.assertTrue(forbidden.isdisjoint(item))

    def test_general_notification_has_null_student_and_navigation_defaults(self):
        self.authenticate()
        data = self.client.get(self.detail_url(self.older)).data["data"]
        self.assertIsNone(data["student"])
        self.assertEqual(
            data["data"],
            {"student_id": None, "resource_type": "", "resource_id": None},
        )

    def test_is_read_filters_accept_only_literal_booleans(self):
        now = timezone.now()
        Notification.objects.filter(pk=self.older.pk).update(
            is_read=True, read_at=now
        )
        self.authenticate()
        read = self.client.get(f"{self.list_url}?is_read=true")
        unread = self.client.get(f"{self.list_url}?is_read=false")
        self.assertEqual(
            {item["id"] for item in read.data["data"]["results"]},
            {str(self.older.id)},
        )
        self.assertEqual(
            {item["id"] for item in unread.data["data"]["results"]},
            {str(self.newer.id)},
        )
        for value in ("1", "0", "yes", "no", "test", ""):
            response = self.client.get(f"{self.list_url}?is_read={value}")
            self.assertEqual(response.status_code, 400, value)

    def test_pagination_page_size_and_maximum(self):
        Notification.objects.bulk_create(
            [
                Notification(
                    recipient=self.guardian,
                    notification_type=Notification.NotificationType.GENERAL,
                    title=f"Bulk {index}",
                    body="Body",
                )
                for index in range(103)
            ]
        )
        self.authenticate()
        default = self.client.get(self.list_url)
        second = self.client.get(f"{self.list_url}?page=2&page_size=10")
        capped = self.client.get(f"{self.list_url}?page_size=1000")
        self.assertEqual(len(default.data["data"]["results"]), 20)
        self.assertEqual(len(second.data["data"]["results"]), 10)
        self.assertEqual(len(capped.data["data"]["results"]), 100)

    def test_list_meta_merges_counts_with_requester_role(self):
        self.authenticate()
        response = self.client.get(f"{self.list_url}?page_size=1")
        self.assertEqual(
            response.data["meta"],
            {
                "unread_count": 2,
                "page": 1,
                "page_size": 1,
                "count": 2,
                "requester_role": {
                    "code": "guardian",
                    "label": self.guardian.get_role_display(),
                },
            },
        )
        detail = self.client.get(self.detail_url(self.newer))
        self.assertEqual(
            detail.data["meta"],
            {
                "requester_role": {
                    "code": "guardian",
                    "label": self.guardian.get_role_display(),
                }
            },
        )

    def test_detail_is_scoped_and_does_not_mark_read(self):
        self.authenticate()
        own = self.client.get(self.detail_url(self.newer))
        other = self.client.get(self.detail_url(self.other))
        missing = self.client.get(f"{self.list_url}{uuid.uuid4()}/")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(other.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.newer.refresh_from_db()
        self.assertFalse(self.newer.is_read)
        self.assertIsNone(self.newer.read_at)

    def test_mobile_authentication_boundaries(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.list_url).status_code, 401)

        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        self.assertEqual(self.client.get(self.list_url).status_code, 403)

        inactive = self.make_guardian("inactive-notification-guardian")
        inactive_client = APIClient()
        self.authenticate(user=inactive, api_client=inactive_client)
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        self.assertEqual(inactive_client.get(self.list_url).status_code, 401)

    def test_mark_read_is_idempotent_and_scoped(self):
        self.authenticate()
        first = self.client.post(f"{self.detail_url(self.newer)}read/")
        self.newer.refresh_from_db()
        original_read_at = self.newer.read_at
        original_updated_at = self.newer.updated_at
        second = self.client.post(f"{self.detail_url(self.newer)}read/")
        self.newer.refresh_from_db()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(self.newer.is_read)
        self.assertIsNotNone(original_read_at)
        self.assertEqual(self.newer.read_at, original_read_at)
        self.assertEqual(self.newer.updated_at, original_updated_at)
        self.assertEqual(
            self.client.post(f"{self.detail_url(self.other)}read/").status_code,
            404,
        )

    def test_read_all_updates_only_current_guardian_unread(self):
        old_time = timezone.now() - timedelta(days=2)
        already_read = self.make_notification(
            title="Already read", is_read=True, read_at=old_time
        )
        self.authenticate()
        response = self.client.post(f"{self.list_url}read-all/")

        self.older.refresh_from_db()
        self.newer.refresh_from_db()
        already_read.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], {"updated_count": 2})
        self.assertTrue(self.older.is_read)
        self.assertTrue(self.newer.is_read)
        self.assertEqual(already_read.read_at, old_time)
        self.assertFalse(self.other.is_read)

        empty = self.client.post(f"{self.list_url}read-all/")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.data["data"], {"updated_count": 0})

    def test_unread_count_is_scoped(self):
        self.authenticate()
        response = self.client.get(f"{self.list_url}unread-count/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], {"unread_count": 2})

    def test_notification_content_methods_are_not_allowed(self):
        self.authenticate()
        self.assertEqual(self.client.post(self.list_url, {}).status_code, 405)
        for method in ("put", "patch", "delete"):
            response = getattr(self.client, method)(
                self.detail_url(self.newer), {}, format="json"
            )
            self.assertEqual(response.status_code, 405)
