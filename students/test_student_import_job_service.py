from datetime import date
from io import BytesIO
import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from openpyxl import Workbook

from academics.models import AcademicYear, GradeLevel, Section
from finance.models import StudentFinancialAccount
from students.models import (
    Enrollment,
    GuardianStudent,
    Student,
    StudentHealthProfile,
    StudentImportJob,
    StudentImportRow,
)
from students.student_import_excel import EXPECTED_HEADERS, IMPORT_SHEET_NAME
from students.student_import_job_service import create_student_import_job


User = get_user_model()


def student_row(**overrides):
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
        "زمرة الدم": "",
        "الأمراض المزمنة": "",
        "الحساسية": "",
        "الأدوية الدائمة": "",
        "الاحتياجات الصحية الخاصة": "",
        "اسم جهة اتصال للطوارئ": "",
        "هاتف الطوارئ": "",
        "ملاحظات صحية": "",
        "السنة الدراسية *": "2026/2027",
        "المرحلة *": "الابتدائية",
        "الصف *": "الصف الثالث",
        "الشعبة *": "أ",
        "تاريخ التسجيل *": "2026-09-01",
        "طريقة الحضور المعتادة": "",
        "طريقة الانصراف المعتادة": "",
    }
    values.update(overrides)
    return [values[header] for header in EXPECTED_HEADERS]


def xlsx_file(*rows, blank_rows_before=0, sheet_name=IMPORT_SHEET_NAME):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(list(EXPECTED_HEADERS))
    for _ in range(blank_rows_before):
        sheet.append([None] * len(EXPECTED_HEADERS))
    for row in rows:
        sheet.append(list(row))
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    output.name = "students.xlsx"
    return output


class StudentImportJobServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(
            username="student-import-creator",
            role=User.Role.SCHOOL_ADMIN,
        )
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

    def create_job(self, uploaded_file, **kwargs):
        return create_student_import_job(
            uploaded_file=uploaded_file,
            created_by=self.creator,
            **kwargs,
        )

    def test_valid_file_creates_ready_job_and_rows(self):
        uploaded_file = xlsx_file(
            student_row(**{"الاسم الأول بالعربية *": "رامي"}),
            student_row(**{"الاسم الأول بالعربية *": "سامي"}),
        )
        expected_hash = hashlib.sha256(uploaded_file.getvalue()).hexdigest()

        result = self.create_job(uploaded_file)
        job = result.job

        self.assertTrue(result.created)
        self.assertEqual(job.status, StudentImportJob.Status.READY)
        self.assertEqual(job.original_filename, "students.xlsx")
        self.assertEqual(job.file_sha256, expected_hash)
        self.assertEqual(job.file_size, len(uploaded_file.getvalue()))
        self.assertEqual(job.rows.count(), 2)
        self.assertEqual(
            set(job.rows.values_list("status", flat=True)),
            {StudentImportRow.Status.READY},
        )

    def test_original_excel_row_numbers_are_persisted(self):
        result = self.create_job(
            xlsx_file(student_row(), blank_rows_before=2)
        )

        self.assertEqual(
            list(result.job.rows.values_list("row_number", flat=True)),
            [4],
        )

    def test_job_counters_match_persisted_rows(self):
        result = self.create_job(
            xlsx_file(
                student_row(**{"الاسم الأول بالعربية *": "رامي"}),
                student_row(
                    **{
                        "الاسم الأول بالعربية *": "سامي",
                        "السنة الدراسية *": "2030/2031",
                    }
                ),
            )
        )
        job = result.job

        self.assertEqual(job.total_rows, job.rows.count())
        self.assertEqual(
            job.valid_rows,
            job.rows.filter(status=StudentImportRow.Status.READY).count(),
        )
        self.assertEqual(
            job.invalid_rows,
            job.rows.filter(status=StudentImportRow.Status.INVALID).count(),
        )
        self.assertEqual(
            job.review_rows,
            job.rows.filter(status=StudentImportRow.Status.REVIEW_REQUIRED).count(),
        )

    def test_invalid_row_creates_validation_failed_job(self):
        result = self.create_job(
            xlsx_file(student_row(**{"السنة الدراسية *": "2030/2031"}))
        )

        self.assertEqual(result.job.status, StudentImportJob.Status.VALIDATION_FAILED)
        self.assertEqual(result.job.invalid_rows, 1)
        self.assertEqual(result.job.rows.get().status, StudentImportRow.Status.INVALID)
        self.assertIn(
            "academic_year_not_found",
            {error["code"] for error in result.job.rows.get().validation_errors},
        )

    def test_review_required_row_creates_validation_failed_job(self):
        Student.objects.create(
            first_name="رامي",
            last_name="اختبار",
            father_name="اسم مختلف",
            birth_date=date(2018, 5, 10),
            gender=Student.Gender.MALE,
        )

        result = self.create_job(xlsx_file(student_row()))

        self.assertEqual(result.job.status, StudentImportJob.Status.VALIDATION_FAILED)
        self.assertEqual(result.job.review_rows, 1)
        self.assertEqual(
            result.job.rows.get().status,
            StudentImportRow.Status.REVIEW_REQUIRED,
        )

    def test_structural_failure_does_not_create_job(self):
        result = self.create_job(
            xlsx_file(student_row(), sheet_name="ورقة خاطئة")
        )

        self.assertFalse(result.created)
        self.assertEqual(StudentImportJob.objects.count(), 0)
        self.assertEqual(StudentImportRow.objects.count(), 0)
        self.assertEqual(result.file_errors[0].code, "missing_sheet")

    def test_row_persistence_failure_rolls_back_job_and_rows(self):
        with patch(
            "students.student_import_job_service.StudentImportRow.objects.bulk_create",
            side_effect=IntegrityError("simulated row failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.create_job(xlsx_file(student_row()))

        self.assertEqual(StudentImportJob.objects.count(), 0)
        self.assertEqual(StudentImportRow.objects.count(), 0)

    def test_dates_and_resolved_references_are_json_safe(self):
        result = self.create_job(xlsx_file(student_row()))
        persisted = result.job.rows.get().normalized_data

        self.assertEqual(persisted["student"]["birth_date"], "2018-05-10")
        self.assertEqual(persisted["enrollment"]["enrollment_date"], "2026-09-01")
        self.assertEqual(
            persisted["resolved_references"]["academic_year_id"],
            str(self.academic_year.id),
        )
        self.assertEqual(
            persisted["resolved_references"]["grade_level_id"],
            str(self.grade.id),
        )
        self.assertEqual(
            persisted["resolved_references"]["section_id"],
            str(self.section.id),
        )

    def test_corrected_file_can_be_uploaded_after_failed_validation(self):
        failed = self.create_job(
            xlsx_file(student_row(**{"السنة الدراسية *": "2030/2031"}))
        )
        corrected = self.create_job(xlsx_file(student_row()))

        self.assertEqual(failed.job.status, StudentImportJob.Status.VALIDATION_FAILED)
        self.assertEqual(corrected.job.status, StudentImportJob.Status.READY)
        self.assertEqual(StudentImportJob.objects.count(), 2)

    def test_validation_persistence_creates_no_final_school_or_finance_data(self):
        before = {
            "users": User.objects.count(),
            "students": Student.objects.count(),
            "profiles": StudentHealthProfile.objects.count(),
            "guardian_links": GuardianStudent.objects.count(),
            "enrollments": Enrollment.objects.count(),
            "financial_accounts": StudentFinancialAccount.objects.count(),
        }

        result = self.create_job(xlsx_file(student_row()))

        self.assertTrue(result.created)
        self.assertEqual(User.objects.count(), before["users"])
        self.assertEqual(Student.objects.count(), before["students"])
        self.assertEqual(StudentHealthProfile.objects.count(), before["profiles"])
        self.assertEqual(GuardianStudent.objects.count(), before["guardian_links"])
        self.assertEqual(Enrollment.objects.count(), before["enrollments"])
        self.assertEqual(
            StudentFinancialAccount.objects.count(),
            before["financial_accounts"],
        )
