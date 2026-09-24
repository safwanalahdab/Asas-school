from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, GuardianStudent, Student, StudentHealthProfile
from students.student_import_excel import (
    StudentImportReadResult,
    StudentImportRowResult,
)
from students.student_import_reference_validation import (
    STATUS_INVALID,
    STATUS_READY,
    STATUS_REVIEW_REQUIRED,
    validate_student_import_references,
)


User = get_user_model()


def error_codes(row):
    return {error.code for error in row.validation_errors}


class StudentImportReferenceValidationTests(TestCase):
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

    def normalized_data(
        self,
        *,
        first_name="رامي",
        last_name="اختبار",
        father_name="ماهر",
        mother_name="هند",
        birth_date_value="2018-05-10",
        gender="male",
        academic_year="2026/2027",
        stage=GradeLevel.Stage.PRIMARY,
        grade_level="الصف الثالث",
        section="أ",
        guardian=None,
    ):
        return {
            "student": {
                "first_name": first_name,
                "last_name": last_name,
                "first_name_en": "",
                "last_name_en": "",
                "father_name": father_name,
                "mother_name": mother_name,
                "birth_date": birth_date_value,
                "gender": gender,
            },
            "guardian": guardian,
            "health_profile": {
                "blood_type": "",
                "chronic_diseases": "",
                "allergies": "",
                "permanent_medications": "",
                "special_health_needs": "",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "health_notes": "",
            },
            "enrollment": {
                "academic_year": academic_year,
                "stage": stage,
                "grade_level": grade_level,
                "section": section,
                "enrollment_date": "2026-09-01",
                "usual_arrival_method": "school_bus",
                "usual_departure_method": "school_bus",
            },
        }

    def read_result(self, *data_rows):
        rows = [
            StudentImportRowResult(
                excel_row_number=index + 2,
                normalized_data=data,
                validation_errors=[],
            )
            for index, data in enumerate(data_rows)
        ]
        return StudentImportReadResult(
            data_row_count=len(rows),
            rows=rows,
            file_errors=[],
        )

    def validate(self, *data_rows):
        return validate_student_import_references(self.read_result(*data_rows))

    def guardian_data(
        self,
        national_id="01234567890",
        first_name="ماهر",
        last_name="اختبار",
        phone_number="0933111222",
    ):
        return {
            "national_id": national_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": phone_number,
            "relationship": "أب",
        }

    def test_existing_academic_references_are_resolved(self):
        result = self.validate(self.normalized_data())
        row = result.rows[0]

        self.assertTrue(result.is_ready)
        self.assertEqual(row.status, STATUS_READY)
        self.assertEqual(row.resolved_references.academic_year_id, str(self.academic_year.id))
        self.assertEqual(row.resolved_references.grade_level_id, str(self.grade.id))
        self.assertEqual(row.resolved_references.section_id, str(self.section.id))

    def test_missing_and_ambiguous_academic_years_are_invalid(self):
        missing = self.validate(
            self.normalized_data(academic_year="2030/2031")
        )

        AcademicYear.objects.create(
            start_date=date(2026, 1, 1),
            end_date=date(2027, 1, 1),
            status=AcademicYear.Status.DRAFT,
        )
        ambiguous = self.validate(self.normalized_data())

        self.assertIn("academic_year_not_found", error_codes(missing.rows[0]))
        self.assertIn("academic_year_ambiguous", error_codes(ambiguous.rows[0]))
        self.assertEqual(missing.rows[0].status, STATUS_INVALID)
        self.assertEqual(ambiguous.rows[0].status, STATUS_INVALID)

    def test_closed_academic_year_cannot_receive_enrollment(self):
        AcademicYear.objects.filter(pk=self.academic_year.pk).update(
            status=AcademicYear.Status.CLOSED
        )

        result = self.validate(self.normalized_data())

        self.assertIn("academic_year_closed", error_codes(result.rows[0]))

    def test_missing_or_mismatched_grade_and_section_are_invalid(self):
        missing_grade = self.validate(
            self.normalized_data(grade_level="الصف غير الموجود")
        )
        missing_section = self.validate(
            self.normalized_data(section="الشعبة غير الموجودة")
        )
        mismatched_stage = self.validate(
            self.normalized_data(stage=GradeLevel.Stage.SECONDARY)
        )

        self.assertIn("grade_level_not_found", error_codes(missing_grade.rows[0]))
        self.assertIn("section_not_found", error_codes(missing_section.rows[0]))
        self.assertIn("grade_level_not_found", error_codes(mismatched_stage.rows[0]))

    def test_new_student_without_suspicion_is_ready(self):
        result = self.validate(self.normalized_data())

        self.assertEqual(result.rows[0].status, STATUS_READY)
        self.assertTrue(result.is_ready)

    def test_similar_students_in_file_require_review(self):
        result = self.validate(
            self.normalized_data(),
            self.normalized_data(),
        )

        self.assertFalse(result.is_ready)
        self.assertEqual(result.review_rows, 2)
        self.assertTrue(
            all(row.status == STATUS_REVIEW_REQUIRED for row in result.rows)
        )
        self.assertTrue(
            all("possible_duplicate_in_file" in error_codes(row) for row in result.rows)
        )

    def test_missing_parent_names_do_not_hide_in_file_suspicion(self):
        result = self.validate(
            self.normalized_data(father_name="", mother_name=""),
            self.normalized_data(),
        )

        self.assertEqual(result.review_rows, 2)

    def test_different_parent_names_do_not_hide_in_file_suspicion(self):
        result = self.validate(
            self.normalized_data(father_name="ماهر", mother_name="هند"),
            self.normalized_data(father_name="فراس", mother_name="سعاد"),
        )

        self.assertFalse(result.is_ready)
        self.assertEqual(result.review_rows, 2)
        self.assertTrue(
            all(row.status == STATUS_REVIEW_REQUIRED for row in result.rows)
        )

    def test_similar_student_in_database_requires_review(self):
        Student.objects.create(
            first_name="رامي",
            last_name="اختبار",
            father_name="ماهر",
            mother_name="هند",
            birth_date=date(2018, 5, 10),
            gender=Student.Gender.MALE,
        )

        result = self.validate(self.normalized_data())

        self.assertEqual(result.rows[0].status, STATUS_REVIEW_REQUIRED)
        self.assertIn("possible_existing_student", error_codes(result.rows[0]))

    def test_missing_parent_name_does_not_hide_database_suspicion(self):
        Student.objects.create(
            first_name="رامي",
            last_name="اختبار",
            father_name="ماهر",
            mother_name="هند",
            birth_date=date(2018, 5, 10),
            gender=Student.Gender.MALE,
        )

        result = self.validate(
            self.normalized_data(father_name="", mother_name="")
        )

        self.assertEqual(result.rows[0].status, STATUS_REVIEW_REQUIRED)

    def test_different_parent_name_does_not_hide_database_suspicion(self):
        Student.objects.create(
            first_name="رامي",
            last_name="اختبار",
            father_name="ماهر",
            mother_name="هند",
            birth_date=date(2018, 5, 10),
            gender=Student.Gender.MALE,
        )

        result = self.validate(
            self.normalized_data(father_name="فراس", mother_name="سعاد")
        )

        self.assertEqual(result.rows[0].status, STATUS_REVIEW_REQUIRED)
        self.assertIn("possible_existing_student", error_codes(result.rows[0]))

    def test_new_guardian_is_marked_for_later_creation(self):
        result = self.validate(
            self.normalized_data(guardian=self.guardian_data())
        )

        self.assertTrue(result.is_ready)
        self.assertEqual(
            result.rows[0].resolved_references.guardian_resolution,
            "new",
        )
        self.assertIsNone(result.rows[0].resolved_references.guardian_user_id)

    def test_existing_guardian_is_resolved_without_modification(self):
        guardian = User.objects.create_user(
            username="existing-guardian",
            national_id="01234567890",
            role=User.Role.GUARDIAN,
            first_name="ماهر",
            last_name="اختبار",
            phone_number="0933111222",
        )
        original_password = guardian.password

        result = self.validate(
            self.normalized_data(guardian=self.guardian_data())
        )
        guardian.refresh_from_db()

        self.assertTrue(result.is_ready)
        self.assertEqual(
            result.rows[0].resolved_references.guardian_user_id,
            str(guardian.id),
        )
        self.assertEqual(guardian.password, original_password)

    def test_non_guardian_role_and_existing_data_conflict_are_invalid(self):
        User.objects.create_user(
            username="teacher-national-id",
            national_id="11111111111",
            role=User.Role.TEACHER,
            first_name="ماهر",
            last_name="اختبار",
        )
        User.objects.create_user(
            username="existing-guardian",
            national_id="22222222222",
            role=User.Role.GUARDIAN,
            first_name="اسم",
            last_name="مختلف",
        )

        result = self.validate(
            self.normalized_data(
                first_name="رامي",
                guardian=self.guardian_data(national_id="11111111111"),
            ),
            self.normalized_data(
                first_name="سامي",
                guardian=self.guardian_data(national_id="22222222222"),
            ),
        )

        self.assertIn(
            "guardian_national_id_role_conflict",
            error_codes(result.rows[0]),
        )
        self.assertIn("guardian_data_conflict", error_codes(result.rows[1]))
        self.assertEqual(result.invalid_rows, 2)

    def test_siblings_can_share_one_consistent_guardian(self):
        guardian = self.guardian_data()

        result = self.validate(
            self.normalized_data(first_name="رامي", guardian=guardian),
            self.normalized_data(first_name="سامي", guardian=dict(guardian)),
        )

        self.assertTrue(result.is_ready)
        self.assertTrue(
            all(
                row.resolved_references.guardian_resolution == "new"
                for row in result.rows
            )
        )

    def test_conflicting_guardian_data_marks_all_siblings_invalid(self):
        result = self.validate(
            self.normalized_data(
                first_name="رامي",
                guardian=self.guardian_data(first_name="ماهر"),
            ),
            self.normalized_data(
                first_name="سامي",
                guardian=self.guardian_data(first_name="فراس"),
            ),
        )

        self.assertEqual(result.invalid_rows, 2)
        self.assertTrue(
            all("guardian_conflict_in_file" in error_codes(row) for row in result.rows)
        )

    def test_student_without_guardian_is_ready(self):
        result = self.validate(self.normalized_data(guardian=None))

        self.assertTrue(result.is_ready)
        self.assertIsNone(result.rows[0].resolved_references.guardian_resolution)

    def test_any_invalid_or_review_row_prevents_whole_file_readiness(self):
        invalid = self.validate(
            self.normalized_data(first_name="رامي"),
            self.normalized_data(
                first_name="سامي",
                academic_year="2030/2031",
            ),
        )

        Student.objects.create(
            first_name="موجود",
            last_name="اختبار",
            birth_date=date(2018, 5, 10),
            gender=Student.Gender.MALE,
        )
        review = self.validate(
            self.normalized_data(first_name="جديد"),
            self.normalized_data(first_name="موجود"),
        )

        self.assertFalse(invalid.is_ready)
        self.assertEqual(invalid.invalid_rows, 1)
        self.assertFalse(review.is_ready)
        self.assertEqual(review.review_rows, 1)

    def test_validation_does_not_create_or_modify_final_data(self):
        guardian = User.objects.create_user(
            username="existing-guardian",
            national_id="01234567890",
            role=User.Role.GUARDIAN,
            first_name="ماهر",
            last_name="اختبار",
            phone_number="0933111222",
        )
        before = {
            "users": User.objects.count(),
            "students": Student.objects.count(),
            "profiles": StudentHealthProfile.objects.count(),
            "links": GuardianStudent.objects.count(),
            "enrollments": Enrollment.objects.count(),
        }

        result = self.validate(
            self.normalized_data(guardian=self.guardian_data())
        )

        self.assertTrue(result.is_ready)
        self.assertEqual(User.objects.count(), before["users"])
        self.assertEqual(Student.objects.count(), before["students"])
        self.assertEqual(StudentHealthProfile.objects.count(), before["profiles"])
        self.assertEqual(GuardianStudent.objects.count(), before["links"])
        self.assertEqual(Enrollment.objects.count(), before["enrollments"])
        guardian.refresh_from_db()
        self.assertEqual(guardian.first_name, "ماهر")

    def test_reference_loading_uses_bounded_query_count(self):
        guardian = User.objects.create_user(
            username="existing-guardian",
            national_id="01234567890",
            role=User.Role.GUARDIAN,
            first_name="ماهر",
            last_name="اختبار",
            phone_number="0933111222",
        )
        rows = [
            self.normalized_data(
                first_name=f"طالب {index}",
                guardian=self.guardian_data(national_id=guardian.national_id),
            )
            for index in range(20)
        ]

        with self.assertNumQueries(5):
            result = self.validate(*rows)

        self.assertTrue(result.is_ready)
