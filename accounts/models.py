import uuid

from django.contrib.auth.models import (
    AbstractUser,
    UserManager as DjangoUserManager,
)
from django.db import models
from django.db.models.functions import Lower


class UserManager(DjangoUserManager):
    """
    مدير مخصص لإنشاء المستخدمين.

    نحافظ على منطق Django الأصلي، لكن نستثني
    الـSuperuser من دورة كلمة المرور المؤقتة.
    """

    def create_superuser(
        self,
        username,
        email=None,
        password=None,
        **extra_fields,
    ):
        # الـSuperuser يحدد كلمة مرور دائمة أثناء إنشائه،
        # لذلك لا نطلب منه تغييرها عند أول دخول.
        extra_fields.setdefault(
            "must_change_password",
            False,
        )

        # لا يوجد تاريخ انتهاء لأن كلمة مرور
        # الـSuperuser ليست مؤقتة.
        extra_fields.setdefault(
            "temporary_password_expires_at",
            None,
        )

        return super().create_superuser(
            username=username,
            email=email,
            password=password,
            **extra_fields,
        )


class User(AbstractUser):
    class Role(models.TextChoices):
        SCHOOL_ADMIN = "school_admin", "إدارة المدرسة"
        SECRETARIAT = "secretariat", "أمانة السر"
        SUPERVISOR = "supervisor", "الموجّه التربوي"
        TEACHER = "teacher", "المعلّم"
        GUARDIAN = "guardian", "ولي الأمر"
        TECH_SUPPORT = "tech_support", "الدعم التقني"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    email = models.EmailField(
        blank=True,
        null=True,
    )

    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        blank=True,
        default="",
    )

    must_change_password = models.BooleanField(
        default=True,
    )

    temporary_password_expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    token_version = models.PositiveIntegerField(
        default=1,
        editable=False,
    )

    # نربط موديل المستخدم بالـManager المخصص.
    objects = UserManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_superuser=True)
                    | ~models.Q(role="")
                ),
                name="user_role_required_unless_superuser",
            ),
            models.UniqueConstraint(
                Lower("email"),
                condition=(
                    models.Q(email__isnull=False)
                    & ~models.Q(email="")
                ),
                name="unique_user_email_case_insensitive",
            ),
        ]

    def __str__(self):
        return self.get_full_name() or self.username