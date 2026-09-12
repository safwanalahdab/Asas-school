from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from students.models import GuardianStudent, Student
from students.serializers import GuardianStudentSerializer
from students.views import GuardianStudentViewSet


User = get_user_model()


class GuardianRelationshipApiTests(TestCase):
    links_url = "/api/v1/students/guardian-links/"

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="relationship-admin",
            password="Strong!934",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.guardian = User.objects.create_user(
            username="relationship-guardian",
            password="Strong!934",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.other_guardian = User.objects.create_user(
            username="relationship-other-guardian",
            password="Strong!934",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.first_student = self.create_student("أحمد")
        self.second_student = self.create_student("سارة")
        self.blank_student = self.create_student("ليلى")
        self.first_link = GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.first_student,
            relationship="أب",
        )
        self.second_link = GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.second_student,
            relationship="عم",
        )
        self.blank_link = GuardianStudent.objects.create(
            guardian=self.other_guardian,
            student=self.blank_student,
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

    @staticmethod
    def create_student(first_name):
        return Student.objects.create(
            first_name=first_name,
            last_name="تجربة",
            birth_date=date(2018, 1, 1),
            gender=Student.Gender.MALE,
        )

    def test_list_and_retrieve_include_correct_relationship(self):
        response = self.client.get(
            self.links_url,
            {"guardian": str(self.guardian.pk)},
        )

        self.assertEqual(response.status_code, 200)
        relationships = {
            str(item["student"]): item["relationship"]
            for item in response.data["data"]["results"]
        }
        self.assertEqual(
            relationships,
            {
                str(self.first_student.pk): "أب",
                str(self.second_student.pk): "عم",
            },
        )
        detail = self.client.get(f"{self.links_url}{self.first_link.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["relationship"], "أب")

    def test_manual_creation_persists_optional_relationship(self):
        student = self.create_student("نور")

        response = self.client.post(
            self.links_url,
            {
                "guardian": str(self.guardian.pk),
                "student": str(student.pk),
                "relationship": "أم",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        link = GuardianStudent.objects.get(student=student)
        self.assertEqual(link.relationship, "أم")
        self.assertEqual(response.data["data"]["relationship"], "أم")

    def test_blank_relationship_remains_readable(self):
        response = self.client.get(f"{self.links_url}{self.blank_link.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["relationship"], "")

    def test_guardian_filter_still_limits_results(self):
        response = self.client.get(
            self.links_url,
            {"guardian": str(self.guardian.pk)},
        )

        ids = {str(item["id"]) for item in response.data["data"]["results"]}
        self.assertEqual(ids, {str(self.first_link.pk), str(self.second_link.pk)})

    def test_link_serialization_uses_select_related_without_per_row_queries(self):
        queryset = GuardianStudent.objects.select_related("guardian", "student")

        with self.assertNumQueries(1):
            data = list(GuardianStudentSerializer(queryset, many=True).data)

        self.assertEqual(len(data), 3)
        self.assertEqual(
            GuardianStudentViewSet.queryset.query.select_related,
            {"guardian": {}, "student": {}},
        )
