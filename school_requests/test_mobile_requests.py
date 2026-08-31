from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from students.models import GuardianStudent, Student

from .mobile_throttles import MobileSchoolRequestBurstThrottle
from .models import SchoolRequest


User = get_user_model()


class MobileSchoolRequestTests(TestCase):
    list_url = "/api/v1/mobile/requests/"

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.guardian = self.make_user("request-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.make_user(
            "request-other-guardian", User.Role.GUARDIAN
        )
        self.admin = self.make_user("request-admin", User.Role.SCHOOL_ADMIN)
        self.supervisor = self.make_user(
            "request-supervisor", User.Role.SUPERVISOR
        )
        self.secretariat = self.make_user(
            "request-secretariat", User.Role.SECRETARIAT
        )
        self.student = self.make_student("Owned", self.guardian)
        self.other_student = self.make_student("Other", self.other_guardian)
        self.inactive_student = self.make_student(
            "Inactive", self.guardian, is_active=False
        )
        self.inactive_link_student = self.make_student(
            "InactiveLink", self.guardian, link_active=False
        )

    def tearDown(self):
        cache.clear()

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username,
            password="StrongPass!493",
            role=role,
            must_change_password=False,
        )

    def make_student(self, first_name, guardian, is_active=True, link_active=True):
        student = Student.objects.create(
            first_name=first_name,
            last_name="Student",
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
            is_active=is_active,
        )
        GuardianStudent.objects.create(
            guardian=guardian,
            student=student,
            is_active=link_active,
        )
        return student

    def authenticate(self, user=None, client="mobile", api_client=None):
        user = user or self.guardian
        api_client = api_client or self.client
        token = RefreshToken.for_user(user)
        token["client"] = client
        token["token_version"] = user.token_version
        api_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token.access_token}"
        )

    def create_request(self, guardian=None, **kwargs):
        return SchoolRequest.objects.create(
            guardian=guardian or self.guardian,
            request_type=kwargs.pop(
                "request_type", SchoolRequest.RequestType.COMPLAINT
            ),
            details=kwargs.pop("details", "Request details"),
            **kwargs,
        )

    def detail_url(self, school_request):
        return f"{self.list_url}{school_request.id}/"

    def response_items(self, response):
        data = response.data["data"]
        return data["results"] if isinstance(data, dict) and "results" in data else data

    def recursive_keys(self, value):
        if isinstance(value, dict):
            keys = set(value)
            for child in value.values():
                keys.update(self.recursive_keys(child))
            return keys
        if isinstance(value, list):
            keys = set()
            for child in value:
                keys.update(self.recursive_keys(child))
            return keys
        return set()

    def test_guardian_creates_all_request_types(self):
        self.authenticate()
        for request_type in (
            SchoolRequest.RequestType.COMPLAINT,
            SchoolRequest.RequestType.INQUIRY,
            SchoolRequest.RequestType.SUGGESTION,
        ):
            cache.clear()
            response = self.client.post(
                self.list_url,
                {"request_type": request_type, "details": f"{request_type} details"},
                format="json",
            )
            self.assertEqual(response.status_code, 201)
            saved = SchoolRequest.objects.get(id=response.data["data"]["id"])
            self.assertEqual(saved.request_type, request_type)
            self.assertEqual(saved.guardian, self.guardian)
            self.assertEqual(saved.status, SchoolRequest.Status.NEW)
            self.assertIsNone(saved.student)
            self.assertIsNone(response.data["data"]["student_display"])

    def test_guardian_creates_request_for_owned_student(self):
        self.authenticate()
        response = self.client.post(
            self.list_url,
            {
                "request_type": SchoolRequest.RequestType.COMPLAINT,
                "details": "Student request",
                "student": str(self.student.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            str(response.data["data"]["student"]),
            str(self.student.id),
        )
        self.assertEqual(
            response.data["data"]["student_display"],
            {"id": str(self.student.id), "name": self.student.full_name},
        )

    def test_unowned_inactive_student_and_inactive_link_are_rejected(self):
        self.authenticate()
        for student in (
            self.other_student,
            self.inactive_student,
            self.inactive_link_student,
        ):
            cache.clear()
            response = self.client.post(
                self.list_url,
                {
                    "request_type": SchoolRequest.RequestType.INQUIRY,
                    "details": "Invalid student",
                    "student": str(student.id),
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("student", response.data["errors"])

    def test_list_and_retrieve_are_isolated_by_guardian(self):
        own = self.create_request()
        other = self.create_request(guardian=self.other_guardian)
        self.authenticate()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in self.response_items(response)}
        self.assertIn(str(own.id), returned_ids)
        self.assertNotIn(str(other.id), returned_ids)
        self.assertEqual(self.client.get(self.detail_url(own)).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url(other)).status_code, 404)

    def test_mobile_authentication_and_password_gate(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "PASSWORD_CHANGE_REQUIRED")

    def test_server_controlled_fields_cannot_be_injected(self):
        self.authenticate()
        response = self.client.post(
            self.list_url,
            {
                "request_type": SchoolRequest.RequestType.COMPLAINT,
                "details": "Malicious request",
                "guardian": str(self.other_guardian.id),
                "status": SchoolRequest.Status.ANSWERED,
                "school_response": "fake response",
                "handled_by": str(self.admin.id),
                "answered_at": "2026-01-01T00:00:00Z",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        saved = SchoolRequest.objects.get(id=response.data["data"]["id"])
        self.assertEqual(saved.guardian, self.guardian)
        self.assertEqual(saved.status, SchoolRequest.Status.NEW)
        self.assertEqual(saved.school_response, "")
        self.assertIsNone(saved.handled_by)
        self.assertIsNone(saved.answered_at)

    def test_response_contract_excludes_internal_fields(self):
        school_request = self.create_request(student=self.student)
        self.authenticate()
        data = self.client.get(self.detail_url(school_request)).data["data"]
        required = {
            "request_type",
            "request_type_display",
            "details",
            "student",
            "student_display",
            "status",
            "status_display",
            "school_response",
            "answered_at",
            "created_at",
        }
        forbidden = {
            "guardian",
            "guardian_username",
            "handled_by",
            "handled_by_username",
            "updated_at",
        }
        self.assertTrue(required.issubset(data))
        self.assertTrue(forbidden.isdisjoint(self.recursive_keys(data)))

    def answer_with_web_role(self, user):
        school_request = self.create_request()
        web_client = APIClient()
        web_client.force_authenticate(user=user)
        response = web_client.post(
            f"/api/v1/requests/{school_request.id}/answer/",
            {"school_response": "School reply"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        school_request.refresh_from_db()
        self.assertEqual(school_request.status, SchoolRequest.Status.ANSWERED)
        self.assertEqual(school_request.school_response, "School reply")
        self.assertEqual(school_request.handled_by, user)
        self.assertIsNotNone(school_request.answered_at)
        return school_request

    def test_web_admin_reply_is_visible_in_mobile_without_staff_identity(self):
        school_request = self.answer_with_web_role(self.admin)
        self.authenticate()
        data = self.client.get(self.detail_url(school_request)).data["data"]
        self.assertEqual(data["status"], SchoolRequest.Status.ANSWERED)
        self.assertEqual(data["school_response"], "School reply")
        self.assertIsNotNone(data["answered_at"])
        self.assertNotIn("handled_by", self.recursive_keys(data))

    def test_supervisor_and_secretariat_can_answer_through_web(self):
        self.answer_with_web_role(self.supervisor)
        self.answer_with_web_role(self.secretariat)

    def test_mobile_has_no_answer_update_or_delete_capability(self):
        school_request = self.create_request()
        self.authenticate()
        answer = self.client.post(
            f"{self.detail_url(school_request)}answer/",
            {"school_response": "fake"},
            format="json",
        )
        self.assertIn(answer.status_code, (404, 405))
        for method in ("put", "patch", "delete"):
            response = getattr(self.client, method)(
                self.detail_url(school_request), {}, format="json"
            )
            self.assertEqual(response.status_code, 405)

    def test_list_orders_newest_first(self):
        older = self.create_request(details="Older")
        newer = self.create_request(details="Newer")
        now = timezone.now()
        SchoolRequest.objects.filter(pk=older.pk).update(
            created_at=now - timedelta(days=1)
        )
        SchoolRequest.objects.filter(pk=newer.pk).update(created_at=now)
        self.authenticate()
        ids = [item["id"] for item in self.response_items(self.client.get(self.list_url))]
        self.assertEqual(ids[:2], [str(newer.id), str(older.id)])

    def test_burst_throttle_blocks_fourth_post_but_not_get(self):
        school_request = self.create_request()
        self.authenticate()
        statuses = []
        for index in range(4):
            statuses.append(
                self.client.post(
                    self.list_url,
                    {
                        "request_type": SchoolRequest.RequestType.SUGGESTION,
                        "details": f"Burst {index}",
                    },
                    format="json",
                ).status_code
            )
        self.assertEqual(statuses, [201, 201, 201, 429])
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url(school_request)).status_code, 200)

    def test_hourly_throttle_blocks_sixth_post_deterministically(self):
        self.authenticate()
        with patch.object(
            MobileSchoolRequestBurstThrottle,
            "get_rate",
            return_value="100/minute",
        ):
            statuses = [
                self.client.post(
                    self.list_url,
                    {
                        "request_type": SchoolRequest.RequestType.INQUIRY,
                        "details": f"Hourly {index}",
                    },
                    format="json",
                ).status_code
                for index in range(6)
            ]
        self.assertEqual(statuses, [201, 201, 201, 201, 201, 429])

    def test_throttling_is_user_scoped(self):
        self.authenticate()
        for index in range(3):
            self.assertEqual(
                self.client.post(
                    self.list_url,
                    {
                        "request_type": SchoolRequest.RequestType.COMPLAINT,
                        "details": f"Guardian A {index}",
                    },
                    format="json",
                ).status_code,
                201,
            )
        other_client = APIClient()
        self.authenticate(user=self.other_guardian, api_client=other_client)
        response = other_client.post(
            self.list_url,
            {
                "request_type": SchoolRequest.RequestType.COMPLAINT,
                "details": "Guardian B",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
