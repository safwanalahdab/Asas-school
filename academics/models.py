import uuid

from django.db import models


class AcademicYear(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "مسودة"
        ACTIVE = "active", "فعال"
        CLOSED = "closed", "مغلق"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    start_date = models.DateField()
    end_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "academics_academic_year"

        ordering = [
            "-start_date",
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    end_date__gt=models.F("start_date"),
                ),
                name="academics_year_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "draft",
                        "active",
                        "closed",
                    ],
                ),
                name="academics_year_valid_status",
            ),
            models.UniqueConstraint(
                fields=[
                    "start_date",
                    "end_date",
                ],
                name="academics_year_unique_dates",
            ),
            models.UniqueConstraint(
                fields=[
                    "status",
                ],
                condition=models.Q(
                    status="active",
                ),
                name="academics_year_single_active",
            ),
        ]

    @property
    def name(self):
        return f"{self.start_date.year}/{self.end_date.year}"

    def __str__(self):
        return self.name


class Term(models.Model):
    class Number(models.IntegerChoices):
        FIRST = 1, "الأول"
        SECOND = 2, "الثاني"

    class Status(models.TextChoices):
        DRAFT = "draft", "مسودة"
        ACTIVE = "active", "فعال"
        CLOSED = "closed", "مغلق"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="terms",
    )

    number = models.PositiveSmallIntegerField(
        choices=Number.choices,
    )

    start_date = models.DateField()
    end_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "academics_term"

        ordering = [
            "-academic_year__start_date",
            "number",
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    number__in=[1, 2],
                ),
                name="academics_term_valid_number",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="academics_term_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "active", "closed"]),
                name="academics_term_valid_status",
            ),
            models.UniqueConstraint(
                fields=["academic_year", "number"],
                name="academics_term_unique_number_per_year",
            ),
            models.UniqueConstraint(
                fields=["academic_year"],
                condition=models.Q(status="active"),
                name="academics_term_single_active_per_year",
            ),
        ]

    def __str__(self):
        return f"{self.academic_year} - {self.get_number_display()}"


class GradeLevel(models.Model):
    class Stage(models.TextChoices):
        KINDERGARTEN = "kindergarten", "الروضة"
        PRIMARY = "primary", "الابتدائية"
        PREPARATORY = "preparatory", "الإعدادية"
        SECONDARY = "secondary", "الثانوية"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    stage = models.CharField(
        max_length=40,
        choices=Stage.choices,
    )

    name = models.CharField(
        max_length=100,
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
        db_table = "academics_grade_level"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "stage",
                    "name",
                ],
                name="academics_grade_unique_name_per_stage",
            ),
        ]

    def __str__(self):
        return self.name


class Section(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="sections",
    )

    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.PROTECT,
        related_name="sections",
    )

    name = models.CharField(
        max_length=80,
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
        db_table = "academics_section"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "academic_year",
                    "grade_level",
                    "name",
                ],
                name="academics_section_unique_per_year_grade",
            ),
        ]

    def __str__(self):
        return f"{self.grade_level} - {self.name} - {self.academic_year}"


class Subject(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(
        max_length=150,
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
        db_table = "academics_subject"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "name",
                ],
                name="academics_subject_unique_name",
            ),
        ]

    def __str__(self):
        return self.name


class GradeSubject(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="grade_subjects",
    )

    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.PROTECT,
        related_name="grade_subjects",
    )

    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="grade_subjects",
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
        db_table = "academics_grade_subject"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "academic_year",
                    "grade_level",
                    "subject",
                ],
                name="academics_grade_subject_unique_per_year",
            ),
        ]

    def __str__(self):
        return f"{self.subject} - {self.grade_level} - {self.academic_year}"
