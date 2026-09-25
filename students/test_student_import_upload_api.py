from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from students.models import (
    Enrollment,
    GuardianStudent,
    Student,
    StudentImportJob,
    StudentImportRow,
)
from students.student_import_excel import EXPECTED_HEADERS, IMPORT_SHEET_NAME


User = get_user_model()


class StudentImportUploadApiTests(TestCase):
    endpoint = "/api/v1/students/imports/"

    @classmethod
    def setUpTestData(cls):
        cls.academic_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="الصف الثالث",
        )
        cls.section = Section.objects.create(
            academic_year=cls.academic_year,
            grade_level=cls.grade,
            name="أ",
        )

    def setUp(self):
        self.client = APIClient()

    def authenticate(self, role):
        user = User.objects.create_user(
            username=f"student-import-{role}-{User.objects.count()}",
            password="Strong!934",
            role=role,
            must_change_password=False,
        )
        self.client.force_authenticate(user, token={"client": "web"})
        return user

    def valid_row(self, **overrides):
        values = {
            "الاسم الأول بالعربية *": "رامي",
            "الكنية بالعربية *": "اختبار",
            "الاسم الأول بالإنكليزية": "Rami",
            "الكنية بالإنكليزية": "Test",
            "اسم الأب": "ماهر",
            "اسم الأم": "هند",
            "تاريخ الميلاد *": date(2018, 5, 10),
            "الجنس *": "ذكر",
            "الرقم الوطني لولي الأمر": "",
            "اسم ولي الأمر الأول": "",
            "كنية ولي الأمر": "",
            "رقم هاتف ولي الأمر": "",
            "صلة القرابة": "",
            "زمرة الدم": "O+",
            "الأمراض المزمنة": "",
            "الحساسية": "",
            "الأدوية الدائمة": "",
            "الاحتياجات الصحية الخاصة": "",
            "اسم جهة اتصال للطوارئ": "",
            "هاتف الطوارئ": "",
            "ملاحظات صحية": "",
            "السنة الدراسية *": "2026/2027",
            "المرحلة *": "الابتدائية",
            "الصف *": self.grade.name,
            "الشعبة *": self.section.name,
            "تاريخ التسجيل *": "2026-09-01",
            "طريقة الحضور المعتادة": "",
            "طريقة الانصراف المعتادة": "ولي الأمر",
        }
        values.update(overrides)
        return [values[header] for header in EXPECTED_HEADERS]

    @staticmethod
    def workbook_upload(*rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = IMPORT_SHEET_NAME
        sheet.append(list(EXPECTED_HEADERS))
        for row in rows:
            sheet.append(list(row))
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        return SimpleUploadedFile(
            "students.xlsx",
            output.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

    def upload(self, uploaded_file):
        return self.client.post(
            self.endpoint,
            {"file": uploaded_file},
            format="multipart",
        )

    def test_school_admin_can_upload(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.upload(self.workbook_upload(self.valid_row()))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["status"], StudentImportJob.Status.READY)

    def test_secretariat_can_upload(self):
        self.authenticate(User.Role.SECRETARIAT)

        response = self.upload(self.workbook_upload(self.valid_row()))

        self.assertEqual(response.status_code, 201)

    def test_unauthorized_roles_are_denied(self):
        for role in (
            User.Role.SUPERVISOR,
            User.Role.TEACHER,
            User.Role.ACCOUNTANT,
            User.Role.TECH_SUPPORT,
            User.Role.GUARDIAN,
        ):
            with self.subTest(role=role):
                self.authenticate(role)
                response = self.upload(self.workbook_upload(self.valid_row()))
                self.assertEqual(response.status_code, 403)
        self.assertFalse(StudentImportJob.objects.exists())

    def test_unauthenticated_request_is_denied(self):
        response = self.upload(self.workbook_upload(self.valid_row()))

        self.assertEqual(response.status_code, 401)

    def test_missing_file_returns_validation_error(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.endpoint, {}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.data["errors"])
        self.assertFalse(StudentImportJob.objects.exists())

    def test_valid_excel_creates_ready_job_and_summary(self):
        actor = self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.upload(self.workbook_upload(self.valid_row()))

        self.assertEqual(response.status_code, 201)
        job = StudentImportJob.objects.get()
        self.assertEqual(job.created_by, actor)
        self.assertEqual(job.status, StudentImportJob.Status.READY)
        self.assertEqual(job.rows.count(), 1)
        self.assertEqual(
            response.data["data"],
            {
                "id": str(job.id),
                "status": StudentImportJob.Status.READY,
                "total_rows": 1,
                "ready_rows": 1,
                "invalid_rows": 0,
                "review_required_rows": 0,
                "succeeded_rows": 0,
                "failed_rows": 0,
                "created_at": response.data["data"]["created_at"],
            },
        )

    def test_excel_validation_issue_creates_validation_failed_job(self):
        self.authenticate(User.Role.SECRETARIAT)
        invalid_row = self.valid_row(**{"الجنس *": "غير معروف"})

        response = self.upload(self.workbook_upload(invalid_row))

        self.assertEqual(response.status_code, 201)
        job = StudentImportJob.objects.get()
        self.assertEqual(job.status, StudentImportJob.Status.VALIDATION_FAILED)
        self.assertEqual(response.data["data"]["invalid_rows"], 1)
        self.assertEqual(response.data["data"]["ready_rows"], 0)

    def test_malformed_excel_returns_controlled_validation_error(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)
        malformed = SimpleUploadedFile(
            "students.xlsx",
            b"not an xlsx file",
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

        response = self.upload(malformed)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "STUDENT_IMPORT_FILE_INVALID")
        self.assertIn("file", response.data["errors"])
        self.assertFalse(StudentImportJob.objects.exists())

    def test_upload_does_not_create_school_records(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.upload(self.workbook_upload(self.valid_row()))

        self.assertEqual(response.status_code, 201)
        self.assertFalse(Student.objects.exists())
        self.assertFalse(GuardianStudent.objects.exists())
        self.assertFalse(Enrollment.objects.exists())
        self.assertFalse(User.objects.filter(role=User.Role.GUARDIAN).exists())

    def test_response_does_not_expose_rows_or_internal_fields(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.upload(self.workbook_upload(self.valid_row()))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            set(response.data["data"]),
            {
                "id",
                "status",
                "total_rows",
                "ready_rows",
                "invalid_rows",
                "review_required_rows",
                "succeeded_rows",
                "failed_rows",
                "created_at",
            },
        )
        self.assertEqual(StudentImportRow.objects.count(), 1)
