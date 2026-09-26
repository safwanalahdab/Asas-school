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

    first_name_en = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    last_name_en = models.CharField(
        max_length=100,
        blank=True,
        default="",
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

        permissions = [
            ("register_student", "تسجيل طالب"),
            ("transfer_student", "نقل طالب بين الشعب"),
            ("view_student_profile", "عرض الملف الشامل للطالب"),
        ]

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

    relationship = models.CharField(
        max_length=50,
        blank=True,
        default="",
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


class StudentHealthProfile(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        related_name="health_profile",
    )

    blood_type = models.CharField(
        max_length=10,
        blank=True,
        default="",
    )

    chronic_diseases = models.TextField(
        blank=True,
        default="",
    )

    allergies = models.TextField(
        blank=True,
        default="",
    )

    permanent_medications = models.TextField(
        blank=True,
        default="",
    )

    special_health_needs = models.TextField(
        blank=True,
        default="",
    )

    emergency_contact_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    emergency_contact_phone = models.CharField(
        max_length=30,
        blank=True,
        default="",
    )

    health_notes = models.TextField(
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
        db_table = "students_student_health_profile"

    def __str__(self):
        return f"Health profile - {self.student}"


class Enrollment(models.Model):
    class TransportationMethod(models.TextChoices):
        SCHOOL_BUS = "school_bus", "باص المدرسة"
        GUARDIAN = "guardian", "ولي الأمر"

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

    usual_arrival_method = models.CharField(
        max_length=20,
        choices=TransportationMethod.choices,
        default=TransportationMethod.SCHOOL_BUS,
        null=True,
        blank=True,
    )

    usual_departure_method = models.CharField(
        max_length=20,
        choices=TransportationMethod.choices,
        default=TransportationMethod.SCHOOL_BUS,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "students_enrollment"

        permissions = [
            (
                "correct_enrollment_placement",
                "تصحيح شعبة تسجيل الطالب",
            ),
        ]

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
        return f"{self.student} - " f"{self.section} - " f"{self.academic_year}"


class StudentAuditLog(models.Model):
    class EventType(models.TextChoices):
        SECTION_TRANSFER = (
            "section_transfer",
            "نقل بين الشعب",
        )
        PLACEMENT_CORRECTION = (
            "placement_correction",
            "تصحيح الشعبة",
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

    reason = models.TextField(
        blank=True,
        default="",
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
        return f"{self.get_event_type_display()} - " f"{self.enrollment.student}"


class StudentImportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VALIDATING = "validating", "Validating"
        VALIDATION_FAILED = "validation_failed", "Validation failed"
        READY = "ready", "Ready"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors", "Completed with errors"
        FAILED = "failed", "Failed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="student_import_jobs",
    )
    original_filename = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    file_size = models.BigIntegerField()
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING,
    )
    total_rows = models.IntegerField(default=0)
    valid_rows = models.IntegerField(default=0)
    invalid_rows = models.IntegerField(default=0)
    review_rows = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    succeeded_rows = models.IntegerField(default=0)
    failed_rows = models.IntegerField(default=0)
    batch_size = models.PositiveSmallIntegerField(default=100)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "students_import_job"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(file_size__gte=0),
                name="students_imp_job_file_size_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_rows__gte=0),
                name="students_imp_job_total_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_rows__gte=0),
                name="students_imp_job_valid_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(invalid_rows__gte=0),
                name="students_imp_job_invalid_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(review_rows__gte=0),
                name="students_imp_job_review_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(processed_rows__gte=0),
                name="students_imp_job_processed_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(succeeded_rows__gte=0),
                name="students_imp_job_succeeded_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(failed_rows__gte=0),
                name="students_imp_job_failed_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(batch_size__gte=1, batch_size__lte=100),
                name="students_imp_job_batch_size_range",
            ),
        ]

    def __str__(self):
        return f"{self.original_filename} - {self.get_status_display()}"


class StudentImportRow(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        REVIEW_REQUIRED = "review_required", "Review required"
        INVALID = "invalid", "Invalid"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    job = models.ForeignKey(
        StudentImportJob,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_number = models.IntegerField()
    normalized_data = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    validation_errors = models.JSONField(default=list)
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="import_rows",
        null=True,
        blank=True,
    )
    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="student_import_rows",
        null=True,
        blank=True,
    )
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="import_rows",
        null=True,
        blank=True,
    )
    attempt_count = models.IntegerField(default=0)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "students_import_row"
        constraints = [
            models.UniqueConstraint(
                fields=["job", "row_number"],
                name="students_imp_row_unique_job_row",
            ),
            models.CheckConstraint(
                condition=models.Q(row_number__gte=1),
                name="students_imp_row_number_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__gte=0),
                name="students_imp_row_attempts_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["job", "status", "row_number"],
                name="stud_imp_job_status_row_idx",
            ),
        ]

    def __str__(self):
        return f"{self.job_id} - row {self.row_number}"
