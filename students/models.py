import uuid

from django.db import models

from config import settings

from academics.models import AcademicYear, Section


class Student(models.Model):
    class Gender(models.TextChoices):
        MALE = "male", "ذكر"
        FEMALE = "female", "أنثى"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    first_name = models.CharField(
        max_length=100,
    )

    last_name = models.CharField(
        max_length=100,
    )

    father_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    mother_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    birth_date = models.DateField()

    gender = models.CharField(
        max_length=10,
        choices=Gender.choices,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "students_student"

        ordering = [
            "first_name",
            "last_name",
        ]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.full_name


class GuardianStudent(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guardian_student_links",
        limit_choices_to={
            "role": "guardian",
        },
    )

    student = models.OneToOneField(
        Student,
        on_delete=models.PROTECT,
        related_name="guardian_link",
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "students_guardian_student"

    def __str__(self):
        return f"{self.guardian} - {self.student}"

class Enrollment(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="student_enrollments",
    )

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="student_enrollments",
    )

    enrollment_date = models.DateField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "students_enrollment"

        ordering = [
            "-enrollment_date",
            "-created_at",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "student",
                    "academic_year",
                ],
                name="students_enrollment_unique_student_year",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "academic_year",
                    "section",
                ],
                name="students_enr_year_section_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.student} - "
            f"{self.section} - "
            f"{self.academic_year}"
        )

class StudentAuditLog(models.Model):
    class EventType(models.TextChoices):
        SECTION_TRANSFER = (
            "section_transfer",
            "نقل بين الشعب",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    event_type = models.CharField(
        max_length=50,
        choices=EventType.choices,
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="student_audit_logs",
    )

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="audit_logs",
    )

    old_section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="student_transfer_logs_from",
    )

    new_section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="student_transfer_logs_to",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        db_table = "students_audit_log"

        ordering = [
            "-created_at",
        ]

    def __str__(self):
        return (
            f"{self.get_event_type_display()} - "
            f"{self.enrollment.student}"
        )