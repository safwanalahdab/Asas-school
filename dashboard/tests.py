from django.contrib.auth import get_user_model
from django.test import TestCase

from school_requests.models import SchoolRequest

from .services import get_dashboard_overview


User = get_user_model()


class DashboardUnansweredGuardianRequestsTests(TestCase):
    def setUp(self):
        self.guardian = User.objects.create_user(
            username="dashboard-guardian",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

    def create_request(self, request_type, status=SchoolRequest.Status.NEW):
        return SchoolRequest.objects.create(
            request_type=request_type,
            details="Request details",
            guardian=self.guardian,
            status=status,
        )

    def count(self):
        return get_dashboard_overview()[
            "unanswered_guardian_requests_count"
        ]

    def test_new_complaint_is_counted(self):
        self.create_request(SchoolRequest.RequestType.COMPLAINT)
        self.assertEqual(self.count(), 1)

    def test_new_inquiry_is_counted(self):
        self.create_request(SchoolRequest.RequestType.INQUIRY)
        self.assertEqual(self.count(), 1)

    def test_new_suggestion_is_counted(self):
        self.create_request(SchoolRequest.RequestType.SUGGESTION)
        self.assertEqual(self.count(), 1)

    def test_answered_request_is_excluded(self):
        self.create_request(
            SchoolRequest.RequestType.SUGGESTION,
            status=SchoolRequest.Status.ANSWERED,
        )
        self.assertEqual(self.count(), 0)
