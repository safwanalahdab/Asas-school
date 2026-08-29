from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import AcademicYear, GradeLevel, Section

from .mobile_selectors import get_guardian_children_queryset
from .models import Enrollment, GuardianStudent, Student


User = get_user_model()


class MobileChildrenApiTests(TestCase):
    list_url = "/api/v1/mobile/children/"

    def setUp(self):
        self.client = APIClient()

        self.guardian = User.objects.create_user(
            username="mobile-guardian",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

        self.other_guardian = User.objects.create_user(
            username="other-mobile-guardian",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

        self.active_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )

        self.old_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )

        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="الصف الخامس",
        )

        self.current_section = Section.objects.create(
            academic_year=self.active_year,
            grade_level=self.grade,
            name="الشعبة أ",
        )

        self.old_section = Section.objects.create(
            academic_year=self.old_year,
            grade_level=self.grade,
            name="الشعبة ب",
        )

        self.child_with_current_enrollment = Student.objects.create(
            first_name="أحمد",
            last_name="محمد",
            father_name="محمود",
            mother_name="سارة",
            birth_date=date(2015, 4, 12),
            gender=Student.Gender.MALE,
        )

        self.child_without_current_enrollment = Student.objects.create(
            first_name="ليان",
            last_name="محمد",
            father_name="محمود",
            mother_name="سارة",
            birth_date=date(2017, 6, 20),
            gender=Student.Gender.FEMALE,
        )

        self.child_with_inactive_link = Student.objects.create(
            first_name="رامي",
            last_name="محمد",
            birth_date=date(2016, 3, 10),
            gender=Student.Gender.MALE,
        )

        self.inactive_child = Student.objects.create(
            first_name="نور",
            last_name="محمد",
            birth_date=date(2018, 1, 15),
            gender=Student.Gender.FEMALE,
            is_active=False,
        )

        self.other_family_child = Student.objects.create(
            first_name="كريم",
            last_name="خالد",
            birth_date=date(2015, 8, 1),
            gender=Student.Gender.MALE,
        )

        self.current_link = GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.child_with_current_enrollment,
            is_active=True,
        )

        GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.child_without_current_enrollment,
            is_active=True,
        )

        GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.child_with_inactive_link,
            is_active=False,
        )

        GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.inactive_child,
            is_active=True,
        )

        GuardianStudent.objects.create(
            guardian=self.other_guardian,
            student=self.other_family_child,
            is_active=True,
        )

        self.current_enrollment = Enrollment.objects.create(
            student=self.child_with_current_enrollment,
            academic_year=self.active_year,
            section=self.current_section,
            enrollment_date=date(2026, 9, 1),
            usual_arrival_method=Enrollment.TransportationMethod.SCHOOL_BUS,
            usual_departure_method=Enrollment.TransportationMethod.GUARDIAN,
        )

        # هذا الطالب لديه تسجيل تاريخي فقط،
        # لذلك يجب أن يظهر ولكن current_enrollment تكون null.
        Enrollment.objects.create(
            student=self.child_without_current_enrollment,
            academic_year=self.old_year,
            section=self.old_section,
            enrollment_date=date(2025, 9, 1),
        )

    def create_access_token(
        self,
        *,
        user=None,
        client="mobile",
    ):
        user = user or self.guardian

        refresh = RefreshToken.for_user(user)

        refresh["client"] = client
        refresh["token_version"] = user.token_version

        return str(refresh.access_token)

    def authenticate(
        self,
        *,
        user=None,
        client="mobile",
    ):
        access = self.create_access_token(
            user=user,
            client=client,
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        return access

    def detail_url(self, student):
        return (
            f"/api/v1/mobile/children/"
            f"{student.pk}/"
        )

    def test_guardian_sees_only_active_owned_children(self):
        self.authenticate()

        response = self.client.get(
            self.list_url,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            response.data["success"],
        )

        self.assertEqual(
            response.data["code"],
            "MOBILE_CHILDREN_RETRIEVED",
        )

        returned_ids = {
            item["id"]
            for item in response.data["data"]
        }

        self.assertEqual(
            returned_ids,
            {
                str(self.child_with_current_enrollment.id),
                str(self.child_without_current_enrollment.id),
            },
        )

        self.assertEqual(
            response.data["meta"]["requester_role"],
            {
                "code": "guardian",
                "label": "ولي الأمر",
            },
        )

    def test_current_enrollment_is_returned_from_active_year(self):
        self.authenticate()

        response = self.client.get(
            self.list_url,
        )

        child = next(
            item
            for item in response.data["data"]
            if item["id"]
            == str(self.child_with_current_enrollment.id)
        )

        enrollment = child["current_enrollment"]

        self.assertIsNotNone(
            enrollment,
        )

        self.assertEqual(
            enrollment["id"],
            str(self.current_enrollment.id),
        )

        self.assertEqual(
            enrollment["enrollment_date"],
            "2026-09-01",
        )

        self.assertEqual(
            enrollment["academic_year"],
            {
                "id": str(self.active_year.id),
                "name": "2026/2027",
            },
        )

        self.assertEqual(
            enrollment["grade_level"],
            {
                "id": str(self.grade.id),
                "name": "الصف الخامس",
            },
        )

        self.assertEqual(
            enrollment["section"],
            {
                "id": str(self.current_section.id),
                "name": "الشعبة أ",
            },
        )

        self.assertEqual(
            enrollment["usual_arrival_method"],
            "school_bus",
        )

        self.assertEqual(
            enrollment["usual_arrival_method_display"],
            "باص المدرسة",
        )

        self.assertEqual(
            enrollment["usual_departure_method"],
            "guardian",
        )

        self.assertEqual(
            enrollment["usual_departure_method_display"],
            "ولي الأمر",
        )

    def test_child_without_active_year_enrollment_returns_null(self):
        self.authenticate()

        response = self.client.get(
            self.list_url,
        )

        child = next(
            item
            for item in response.data["data"]
            if item["id"]
            == str(self.child_without_current_enrollment.id)
        )

        self.assertIsNone(
            child["current_enrollment"],
        )

    def test_guardian_can_retrieve_own_child(self):
        self.authenticate()

        response = self.client.get(
            self.detail_url(
                self.child_with_current_enrollment,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.data["code"],
            "MOBILE_CHILD_RETRIEVED",
        )

        self.assertEqual(
            response.data["data"]["id"],
            str(self.child_with_current_enrollment.id),
        )

        self.assertEqual(
            response.data["data"]["full_name"],
            "أحمد محمد",
        )

    def test_unowned_hidden_and_missing_children_return_same_404(self):
        self.authenticate()

        student_ids = (
            self.other_family_child.id,
            self.child_with_inactive_link.id,
            self.inactive_child.id,
            "00000000-0000-0000-0000-000000000000",
        )

        for student_id in student_ids:
            response = self.client.get(
                f"{self.list_url}{student_id}/"
            )

            self.assertEqual(
                response.status_code,
                404,
            )

            self.assertFalse(
                response.data["success"],
            )

            self.assertEqual(
                response.data["code"],
                "MOBILE_CHILD_NOT_FOUND",
            )

            self.assertEqual(
                response.data["message"],
                "لم يتم العثور على الطالب المطلوب.",
            )

    def test_request_without_token_is_rejected(self):
        response = self.client.get(
            self.list_url,
        )

        self.assertEqual(
            response.status_code,
            401,
        )

        self.assertFalse(
            response.data["success"],
        )

    def test_web_token_is_rejected(self):
        self.authenticate(
            client="web",
        )

        response = self.client.get(
            self.list_url,
        )

        self.assertEqual(
            response.status_code,
            401,
        )

    def test_guardian_must_change_password_is_forbidden(self):
        self.guardian.must_change_password = True

        self.guardian.save(
            update_fields=[
                "must_change_password",
            ]
        )

        self.authenticate()

        response = self.client.get(
            self.list_url,
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertEqual(
            response.data["code"],
            "PASSWORD_CHANGE_REQUIRED",
        )

    def test_old_token_after_token_version_change_is_rejected(self):
        old_access = self.create_access_token()

        self.guardian.token_version += 1

        self.guardian.save(
            update_fields=[
                "token_version",
            ]
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {old_access}"
        )

        response = self.client.get(
            self.list_url,
        )

        self.assertEqual(
            response.status_code,
            401,
        )

        self.assertEqual(
            response.data["code"],
            "TOKEN_VERSION_INVALID",
        )

    def test_inactive_guardian_is_rejected(self):
        access = self.create_access_token()

        self.guardian.is_active = False

        self.guardian.save(
            update_fields=[
                "is_active",
            ]
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        response = self.client.get(
            self.list_url,
        )

        self.assertEqual(
            response.status_code,
            401,
        )

    def test_non_guardian_mobile_token_is_forbidden(self):
        teacher = User.objects.create_user(
            username="mobile-children-teacher",
            password="StrongPass!493",
            role=User.Role.TEACHER,
            must_change_password=False,
        )

        self.authenticate(
            user=teacher,
        )

        response = self.client.get(
            self.list_url,
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertEqual(
            response.data["code"],
            "MOBILE_GUARDIAN_ACCESS_DENIED",
        )

    def test_guardian_with_no_children_gets_empty_successful_list(self):
        empty_guardian = User.objects.create_user(
            username="empty-guardian",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

        self.authenticate(
            user=empty_guardian,
        )

        response = self.client.get(
            self.list_url,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.data["code"],
            "MOBILE_CHILDREN_RETRIEVED",
        )

        self.assertEqual(
            response.data["data"],
            [],
        )

    def test_response_exposes_only_mobile_child_fields(self):
        self.authenticate()

        response = self.client.get(
            self.detail_url(
                self.child_with_current_enrollment,
            )
        )

        child = response.data["data"]

        self.assertEqual(
            set(child.keys()),
            {
                "id",
                "first_name",
                "last_name",
                "full_name",
                "father_name",
                "mother_name",
                "birth_date",
                "gender",
                "gender_display",
                "current_enrollment",
            },
        )

        self.assertEqual(
            set(child["current_enrollment"].keys()),
            {
                "id",
                "enrollment_date",
                "academic_year",
                "grade_level",
                "section",
                "usual_arrival_method",
                "usual_arrival_method_display",
                "usual_departure_method",
                "usual_departure_method_display",
            },
        )

        forbidden_fields = {
            "guardian",
            "guardian_link",
            "is_active",
            "created_at",
            "updated_at",
            "password",
            "finance",
            "grades",
            "attendance",
            "behavior",
            "homework",
        }

        self.assertTrue(
            forbidden_fields.isdisjoint(
                child.keys()
            )
        )

    def test_get_requests_do_not_modify_student_data(self):
        self.authenticate()

        student_updated_at = (
            self.child_with_current_enrollment.updated_at
        )

        link_updated_at = (
            self.current_link.updated_at
        )

        enrollment_updated_at = (
            self.current_enrollment.updated_at
        )

        student_count = Student.objects.count()
        link_count = GuardianStudent.objects.count()
        enrollment_count = Enrollment.objects.count()

        list_response = self.client.get(
            self.list_url,
        )

        detail_response = self.client.get(
            self.detail_url(
                self.child_with_current_enrollment,
            )
        )

        self.assertEqual(
            list_response.status_code,
            200,
        )

        self.assertEqual(
            detail_response.status_code,
            200,
        )

        self.child_with_current_enrollment.refresh_from_db()
        self.current_link.refresh_from_db()
        self.current_enrollment.refresh_from_db()

        self.assertEqual(
            self.child_with_current_enrollment.updated_at,
            student_updated_at,
        )

        self.assertEqual(
            self.current_link.updated_at,
            link_updated_at,
        )

        self.assertEqual(
            self.current_enrollment.updated_at,
            enrollment_updated_at,
        )

        self.assertEqual(
            Student.objects.count(),
            student_count,
        )

        self.assertEqual(
            GuardianStudent.objects.count(),
            link_count,
        )

        self.assertEqual(
            Enrollment.objects.count(),
            enrollment_count,
        )

    def test_children_selector_avoids_n_plus_one_queries(self):
        extra_child = Student.objects.create(
            first_name="سليم",
            last_name="محمد",
            birth_date=date(2016, 9, 5),
            gender=Student.Gender.MALE,
        )

        GuardianStudent.objects.create(
            guardian=self.guardian,
            student=extra_child,
            is_active=True,
        )

        Enrollment.objects.create(
            student=extra_child,
            academic_year=self.active_year,
            section=self.current_section,
            enrollment_date=date(2026, 9, 1),
        )

        with self.assertNumQueries(2):
            children = list(
                get_guardian_children_queryset(
                    guardian=self.guardian,
                )
            )

        self.assertEqual(
            len(children),
            3,
        )