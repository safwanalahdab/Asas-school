import uuid

from django.conf import settings
from django.db import models

from academics.models import Section
from students.models import Enrollment


class AttendanceSheet(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="attendance_sheets",
    )

    attendance_date = models.DateField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_attendance_sheets",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "attendance_sheet"

        ordering = [
            "-attendance_date",
            "-created_at",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "section",
                    "attendance_date",
                ],
                name="att_sheet_unique_section_date",
            ),
        ]

    def __str__(self):
        return (
            f"{self.section} - "
            f"{self.attendance_date}"
        )



class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        UNMARKED = "unmarked", "غير محدد"
        PRESENT = "present", "حاضر"
        ABSENT = "absent", "غائب"

    class AbsenceType(models.TextChoices):
        EXCUSED = "excused", "بعذر"
        UNEXCUSED = "unexcused", "دون عذر"

    class AbsenceReasonSource(models.TextChoices):
        GUARDIAN = "guardian", "ولي الأمر"
        SCHOOL = "school", "إدارة المدرسة"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    sheet = models.ForeignKey(
        AttendanceSheet,
        on_delete=models.PROTECT,
        related_name="records",
    )

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNMARKED,
    )

    arrival_time = models.TimeField(
        null=True,
        blank=True,
    )

    arrival_method = models.CharField(
        max_length=20,
        choices=Enrollment.TransportationMethod.choices,
        blank=True,
        default="",
    )

    departure_time = models.TimeField(
        null=True,
        blank=True,
    )

    departure_method = models.CharField(
        max_length=20,
        choices=Enrollment.TransportationMethod.choices,
        blank=True,
        default="",
    )

    absence_type = models.CharField(
        max_length=20,
        choices=AbsenceType.choices,
        blank=True,
        default="",
    )

    absence_reason = models.TextField(
        blank=True,
        default="",
    )

    absence_reason_source = models.CharField(
        max_length=20,
        choices=AbsenceReasonSource.choices,
        blank=True,
        default="",
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "attendance_record"

        ordering = [
            "enrollment__student__first_name",
            "enrollment__student__last_name",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "sheet",
                    "enrollment",
                ],
                name="att_record_unique_sheet_enrollment",
            ),
        ]

    def __str__(self):
        return (
            f"{self.enrollment.student} - "
            f"{self.sheet.attendance_date}"
        )