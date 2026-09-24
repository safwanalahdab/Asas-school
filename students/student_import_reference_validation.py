from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
import re

from django.db.models import Q

from accounts.models import User
from academics.models import AcademicYear, GradeLevel, Section

from .models import Student
from .student_import_excel import (
    HEADER_BY_FIELD,
    ImportValidationError,
    StudentImportReadResult,
)


STATUS_INVALID = "invalid"
STATUS_REVIEW_REQUIRED = "review_required"
STATUS_READY = "ready"

ACADEMIC_YEAR_PATTERN = re.compile(r"^(\d{4})/(\d{4})$")


@dataclass(frozen=True)
class ResolvedStudentImportReferences:
    academic_year_id: str | None = None
    grade_level_id: str | None = None
    section_id: str | None = None
    guardian_user_id: str | None = None
    guardian_resolution: str | None = None

    def to_dict(self):
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class StudentImportReferenceRowResult:
    excel_row_number: int
    normalized_data: dict
    status: str
    validation_errors: list[ImportValidationError]
    resolved_references: ResolvedStudentImportReferences

    def to_dict(self):
        return {
            "excel_row_number": self.excel_row_number,
            "normalized_data": self.normalized_data,
            "status": self.status,
            "validation_errors": [error.to_dict() for error in self.validation_errors],
            "resolved_references": self.resolved_references.to_dict(),
        }


@dataclass(frozen=True)
class StudentImportReferenceValidationResult:
    data_row_count: int
    ready_rows: int
    review_rows: int
    invalid_rows: int
    rows: list[StudentImportReferenceRowResult]
    file_errors: list[ImportValidationError]

    @property
    def is_ready(self):
        return (
            not self.file_errors
            and self.data_row_count > 0
            and self.ready_rows == self.data_row_count
        )

    def to_dict(self):
        return {
            "data_row_count": self.data_row_count,
            "ready_rows": self.ready_rows,
            "review_rows": self.review_rows,
            "invalid_rows": self.invalid_rows,
            "is_ready": self.is_ready,
            "rows": [row.to_dict() for row in self.rows],
            "file_errors": [error.to_dict() for error in self.file_errors],
        }


def _normalized_text(value):
    return " ".join(str(value or "").split()).casefold()


def _issue(code, detail, row_number, field=None):
    return ImportValidationError(
        code=code,
        detail=detail,
        field=field,
        column=HEADER_BY_FIELD.get(field),
        excel_row_number=row_number,
    )


def _year_key(value):
    match = ACADEMIC_YEAR_PATTERN.fullmatch(str(value or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _student_signature(student_data):
    try:
        birth_date = date.fromisoformat(student_data.get("birth_date") or "")
    except (TypeError, ValueError):
        return None
    first_name = _normalized_text(student_data.get("first_name"))
    last_name = _normalized_text(student_data.get("last_name"))
    gender = student_data.get("gender")
    if not first_name or not last_name or not gender:
        return None
    return first_name, last_name, birth_date, gender


def _guardian_core(guardian_data):
    return (
        _normalized_text(guardian_data.get("first_name")),
        _normalized_text(guardian_data.get("last_name")),
        _normalized_text(guardian_data.get("phone_number")),
    )


def _guardian_data_conflicts(first, second):
    first_core = _guardian_core(first)
    second_core = _guardian_core(second)
    if first_core[:2] != second_core[:2]:
        return True
    return bool(first_core[2] and second_core[2] and first_core[2] != second_core[2])


def _existing_guardian_conflicts(guardian_data, user):
    if _normalized_text(guardian_data.get("first_name")) != _normalized_text(user.first_name):
        return True
    if _normalized_text(guardian_data.get("last_name")) != _normalized_text(user.last_name):
        return True
    imported_phone = _normalized_text(guardian_data.get("phone_number"))
    existing_phone = _normalized_text(user.phone_number)
    return bool(imported_phone and imported_phone != existing_phone)


def _load_academic_years(rows):
    year_keys = {
        key
        for row in rows
        if (key := _year_key(row.normalized_data.get("enrollment", {}).get("academic_year")))
    }
    if not year_keys:
        return {}
    years = AcademicYear.objects.filter(
        start_date__year__in={key[0] for key in year_keys},
        end_date__year__in={key[1] for key in year_keys},
    )
    grouped = defaultdict(list)
    for academic_year in years:
        grouped[(academic_year.start_date.year, academic_year.end_date.year)].append(
            academic_year
        )
    return grouped


def _load_grade_levels(rows):
    grade_keys = {
        (
            row.normalized_data.get("enrollment", {}).get("stage"),
            row.normalized_data.get("enrollment", {}).get("grade_level"),
        )
        for row in rows
    }
    grade_keys.discard((None, None))
    if not grade_keys:
        return {}
    grades = GradeLevel.objects.filter(
        stage__in={key[0] for key in grade_keys if key[0]},
        name__in={key[1] for key in grade_keys if key[1]},
    )
    grouped = defaultdict(list)
    for grade in grades:
        grouped[(grade.stage, grade.name)].append(grade)
    return grouped


def _load_guardians(rows):
    national_ids = {
        guardian["national_id"]
        for row in rows
        if (guardian := row.normalized_data.get("guardian"))
        and guardian.get("national_id")
    }
    if not national_ids:
        return {}, {}
    users = User.objects.filter(
        Q(national_id__in=national_ids) | Q(username__in=national_ids)
    ).only(
        "id",
        "username",
        "national_id",
        "role",
        "first_name",
        "last_name",
        "phone_number",
    )
    by_national_id = {}
    username_conflicts = {}
    for user in users:
        if user.national_id in national_ids:
            by_national_id[user.national_id] = user
        if user.username in national_ids and user.national_id != user.username:
            username_conflicts[user.username] = user
    return by_national_id, username_conflicts


def _load_student_candidates(rows):
    signatures = {
        signature
        for row in rows
        if (signature := _student_signature(row.normalized_data.get("student", {})))
    }
    if not signatures:
        return {}
    students = Student.objects.filter(
        birth_date__in={signature[2] for signature in signatures},
        gender__in={signature[3] for signature in signatures},
    ).only(
        "id",
        "first_name",
        "last_name",
        "father_name",
        "mother_name",
        "birth_date",
        "gender",
    )
    grouped = defaultdict(list)
    for student in students:
        signature = _student_signature(
            {
                "first_name": student.first_name,
                "last_name": student.last_name,
                "father_name": student.father_name,
                "mother_name": student.mother_name,
                "birth_date": student.birth_date.isoformat(),
                "gender": student.gender,
            }
        )
        if signature in signatures:
            grouped[signature].append(student)
    return grouped


def _in_file_duplicate_rows(rows):
    grouped = defaultdict(list)
    for row in rows:
        signature = _student_signature(row.normalized_data.get("student", {}))
        if signature:
            grouped[signature].append(row)

    duplicates = set()
    for candidates in grouped.values():
        if len(candidates) > 1:
            duplicates.update(row.excel_row_number for row in candidates)
    return duplicates


def _conflicting_guardian_rows(rows):
    grouped = defaultdict(list)
    for row in rows:
        guardian = row.normalized_data.get("guardian")
        if guardian and guardian.get("national_id"):
            grouped[guardian["national_id"]].append(row)

    conflicts = set()
    for candidates in grouped.values():
        for index, first in enumerate(candidates):
            for second in candidates[index + 1 :]:
                if _guardian_data_conflicts(
                    first.normalized_data["guardian"],
                    second.normalized_data["guardian"],
                ):
                    conflicts.update(row.excel_row_number for row in candidates)
                    break
    return conflicts


def validate_student_import_references(
    read_result: StudentImportReadResult,
) -> StudentImportReferenceValidationResult:
    rows = list(read_result.rows)
    if read_result.file_errors:
        return StudentImportReferenceValidationResult(
            data_row_count=read_result.data_row_count,
            ready_rows=0,
            review_rows=0,
            invalid_rows=read_result.data_row_count,
            rows=[],
            file_errors=list(read_result.file_errors),
        )

    academic_years = _load_academic_years(rows)
    grade_levels = _load_grade_levels(rows)
    guardians, username_conflicts = _load_guardians(rows)
    student_candidates = _load_student_candidates(rows)
    in_file_duplicates = _in_file_duplicate_rows(rows)
    guardian_conflicts = _conflicting_guardian_rows(rows)

    row_contexts = []
    section_keys = set()
    for row in rows:
        enrollment_data = row.normalized_data.get("enrollment", {})
        issues = list(row.validation_errors)
        references = {
            "academic_year": None,
            "grade_level": None,
            "section": None,
            "guardian": None,
            "guardian_resolution": None,
        }

        year_key = _year_key(enrollment_data.get("academic_year"))
        matching_years = academic_years.get(year_key, []) if year_key else []
        if year_key and not matching_years:
            issues.append(
                _issue(
                    "academic_year_not_found",
                    "السنة الدراسية غير موجودة في النظام.",
                    row.excel_row_number,
                    "academic_year",
                )
            )
        elif len(matching_years) > 1:
            issues.append(
                _issue(
                    "academic_year_ambiguous",
                    "تطابق قيمة السنة الدراسية أكثر من سنة في النظام.",
                    row.excel_row_number,
                    "academic_year",
                )
            )
        elif matching_years:
            references["academic_year"] = matching_years[0]
            if matching_years[0].status == AcademicYear.Status.CLOSED:
                issues.append(
                    _issue(
                        "academic_year_closed",
                        "لا يمكن إنشاء تسجيل في سنة دراسية مغلقة.",
                        row.excel_row_number,
                        "academic_year",
                    )
                )

        grade_key = (
            enrollment_data.get("stage"),
            enrollment_data.get("grade_level"),
        )
        matching_grades = grade_levels.get(grade_key, [])
        if all(grade_key) and not matching_grades:
            issues.append(
                _issue(
                    "grade_level_not_found",
                    "المرحلة والصف المحددان غير موجودين أو غير متطابقين.",
                    row.excel_row_number,
                    "grade_level",
                )
            )
        elif len(matching_grades) > 1:
            issues.append(
                _issue(
                    "grade_level_ambiguous",
                    "تطابق المرحلة والصف أكثر من سجل في النظام.",
                    row.excel_row_number,
                    "grade_level",
                )
            )
        elif matching_grades:
            references["grade_level"] = matching_grades[0]

        if references["academic_year"] and references["grade_level"]:
            section_keys.add(
                (
                    references["academic_year"].id,
                    references["grade_level"].id,
                    enrollment_data.get("section"),
                )
            )
        row_contexts.append((row, issues, references))

    sections = defaultdict(list)
    if section_keys:
        for section in Section.objects.filter(
            academic_year_id__in={key[0] for key in section_keys},
            grade_level_id__in={key[1] for key in section_keys},
            name__in={key[2] for key in section_keys if key[2]},
        ).only("id", "academic_year_id", "grade_level_id", "name"):
            sections[
                (section.academic_year_id, section.grade_level_id, section.name)
            ].append(section)

    results = []
    counts = {STATUS_READY: 0, STATUS_REVIEW_REQUIRED: 0, STATUS_INVALID: 0}
    for row, issues, references in row_contexts:
        enrollment_data = row.normalized_data.get("enrollment", {})
        if references["academic_year"] and references["grade_level"]:
            section_key = (
                references["academic_year"].id,
                references["grade_level"].id,
                enrollment_data.get("section"),
            )
            matching_sections = sections.get(section_key, [])
            if not matching_sections:
                issues.append(
                    _issue(
                        "section_not_found",
                        "الشعبة غير موجودة ضمن السنة والصف المحددين.",
                        row.excel_row_number,
                        "section",
                    )
                )
            elif len(matching_sections) > 1:
                issues.append(
                    _issue(
                        "section_ambiguous",
                        "تطابق اسم الشعبة أكثر من سجل ضمن السنة والصف المحددين.",
                        row.excel_row_number,
                        "section",
                    )
                )
            else:
                references["section"] = matching_sections[0]

        guardian_data = row.normalized_data.get("guardian")
        if guardian_data:
            national_id = guardian_data.get("national_id")
            existing_guardian = guardians.get(national_id)
            if row.excel_row_number in guardian_conflicts:
                issues.append(
                    _issue(
                        "guardian_conflict_in_file",
                        "توجد بيانات أساسية متعارضة لولي الأمر نفسه داخل الملف.",
                        row.excel_row_number,
                        "guardian_national_id",
                    )
                )
            if existing_guardian:
                if existing_guardian.role != User.Role.GUARDIAN:
                    issues.append(
                        _issue(
                            "guardian_national_id_role_conflict",
                            "الرقم الوطني مرتبط بحساب لا يخص ولي أمر.",
                            row.excel_row_number,
                            "guardian_national_id",
                        )
                    )
                elif _existing_guardian_conflicts(guardian_data, existing_guardian):
                    issues.append(
                        _issue(
                            "guardian_data_conflict",
                            "بيانات ولي الأمر المدخلة لا تطابق بيانات الحساب الموجود.",
                            row.excel_row_number,
                            "guardian_national_id",
                        )
                    )
                else:
                    references["guardian"] = existing_guardian
                    references["guardian_resolution"] = "existing"
            elif national_id in username_conflicts:
                issues.append(
                    _issue(
                        "guardian_username_conflict",
                        "الرقم الوطني مستخدم كاسم مستخدم لحساب آخر.",
                        row.excel_row_number,
                        "guardian_national_id",
                    )
                )
            else:
                references["guardian_resolution"] = "new"

        review_issues = []
        if row.excel_row_number in in_file_duplicates:
            review_issues.append(
                _issue(
                    "possible_duplicate_in_file",
                    "توجد بيانات طالب مشابهة في صف آخر داخل الملف وتتطلب مراجعة.",
                    row.excel_row_number,
                )
            )

        student_data = row.normalized_data.get("student", {})
        signature = _student_signature(student_data)
        possible_students = student_candidates.get(signature, [])
        if possible_students:
            review_issues.append(
                _issue(
                    "possible_existing_student",
                    "يوجد طالب محتمل التطابق في النظام ويجب مراجعته يدويًا.",
                    row.excel_row_number,
                )
            )

        invalid = bool(issues)
        if invalid:
            status = STATUS_INVALID
        elif review_issues:
            status = STATUS_REVIEW_REQUIRED
        else:
            status = STATUS_READY
        issues.extend(review_issues)
        counts[status] += 1

        results.append(
            StudentImportReferenceRowResult(
                excel_row_number=row.excel_row_number,
                normalized_data=row.normalized_data,
                status=status,
                validation_errors=issues,
                resolved_references=ResolvedStudentImportReferences(
                    academic_year_id=(
                        str(references["academic_year"].id)
                        if references["academic_year"]
                        else None
                    ),
                    grade_level_id=(
                        str(references["grade_level"].id)
                        if references["grade_level"]
                        else None
                    ),
                    section_id=(
                        str(references["section"].id)
                        if references["section"]
                        else None
                    ),
                    guardian_user_id=(
                        str(references["guardian"].id)
                        if references["guardian"]
                        else None
                    ),
                    guardian_resolution=references["guardian_resolution"],
                ),
            )
        )

    return StudentImportReferenceValidationResult(
        data_row_count=read_result.data_row_count,
        ready_rows=counts[STATUS_READY],
        review_rows=counts[STATUS_REVIEW_REQUIRED],
        invalid_rows=counts[STATUS_INVALID],
        rows=results,
        file_errors=list(read_result.file_errors),
    )
