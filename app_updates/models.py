import uuid
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class AppUpdatePolicy(models.Model):
    """
    سياسة تحديث تطبيق أساس لمنصة واحدة.

    القرار (تحديث اختياري/إجباري) يُحسب من أرقام الـBuild فقط
    ولا يُخزن، حتى لا تصبح السياسة متناقضة.
    """

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"

    # كل منصة تقبل فقط روابط متجرها الرسمي عبر HTTPS.
    OFFICIAL_STORE_URL_PREFIXES = {
        Platform.ANDROID: "https://play.google.com/",
        Platform.IOS: "https://apps.apple.com/",
    }

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    platform = models.CharField(
        "المنصة",
        max_length=10,
        choices=Platform.choices,
        unique=True,
        error_messages={"unique": "توجد سياسة تحديث لهذه المنصة مسبقًا."},
    )
    is_check_enabled = models.BooleanField(
        "تفعيل فحص التحديث",
        default=False,
    )
    latest_version = models.CharField(
        "اسم أحدث نسخة",
        max_length=50,
    )
    latest_build = models.PositiveBigIntegerField(
        "رقم أحدث Build",
        validators=[MinValueValidator(1)],
    )
    minimum_supported_build = models.PositiveBigIntegerField(
        "أقل Build مدعوم",
        validators=[MinValueValidator(1)],
    )
    update_message = models.TextField(
        "رسالة التحديث",
        blank=True,
        default="",
    )
    store_url = models.URLField(
        "رابط المتجر الرسمي",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "سياسة تحديث التطبيق"
        verbose_name_plural = "سياسات تحديث التطبيق"
        ordering = ["platform"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(platform__in=["android", "ios"]),
                name="app_updates_policy_valid_platform",
            ),
            models.CheckConstraint(
                condition=models.Q(latest_build__gte=1),
                name="app_updates_policy_latest_build_gte_1",
                violation_error_message="يجب أن يكون رقم أحدث Build أكبر من أو يساوي 1.",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_supported_build__gte=1),
                name="app_updates_policy_min_build_gte_1",
                violation_error_message="يجب أن يكون أقل Build مدعوم أكبر من أو يساوي 1.",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    minimum_supported_build__lte=models.F("latest_build"),
                ),
                name="app_updates_policy_min_lte_latest",
                violation_error_message=(
                    "يجب ألا يتجاوز أقل Build مدعوم رقم أحدث Build."
                ),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        platform="android",
                        store_url__startswith="https://play.google.com/",
                    )
                    | models.Q(
                        platform="ios",
                        store_url__startswith="https://apps.apple.com/",
                    )
                ),
                name="app_updates_policy_official_store_url",
                violation_error_message="رابط المتجر يجب أن يكون الرابط الرسمي لمتجر المنصة.",
            ),
        ]

    def __str__(self):
        return f"{self.get_platform_display()} — {self.latest_version} ({self.latest_build})"

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.latest_build is not None
            and self.minimum_supported_build is not None
            and self.minimum_supported_build > self.latest_build
        ):
            errors["minimum_supported_build"] = (
                "يجب ألا يتجاوز أقل Build مدعوم رقم أحدث Build."
            )

        store_url_error = self._store_url_error()
        if store_url_error:
            errors["store_url"] = store_url_error

        if errors:
            raise ValidationError(errors)

    def _store_url_error(self):
        prefix = self.OFFICIAL_STORE_URL_PREFIXES.get(self.platform)
        if not prefix or not self.store_url:
            # المنصة أو الرابط غير صالحين أصلًا ويتولى clean_fields الإبلاغ.
            return None
        # البادئة تنتهي بـ"/" فتضمن HTTPS والنطاق الرسمي بالضبط،
        # دون منفذ أو بيانات دخول أو نطاق فرعي مضلل.
        if not self.store_url.startswith(prefix):
            return "رابط المتجر يجب أن يكون الرابط الرسمي لمتجر المنصة."
        if urlsplit(self.store_url).path.lower().endswith(".apk"):
            return "لا يُسمح بروابط تنزيل APK المباشرة."
        return None

    def evaluate(self, current_build):
        """يرجع (update_available, force_update) اعتمادًا على Build فقط."""
        if not self.is_check_enabled:
            return False, False
        if current_build < self.minimum_supported_build:
            return True, True
        if current_build < self.latest_build:
            return True, False
        return False, False
