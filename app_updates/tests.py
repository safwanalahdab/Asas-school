from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import AppUpdatePolicy

User = get_user_model()

ANDROID_STORE_URL = "https://play.google.com/store/apps/details?id=com.assas.app"
IOS_STORE_URL = "https://apps.apple.com/app/assas/id1234567890"


def make_policy(**overrides):
    values = {
        "platform": AppUpdatePolicy.Platform.ANDROID,
        "is_check_enabled": True,
        "latest_version": "1.4.0",
        "latest_build": 40,
        "minimum_supported_build": 35,
        "update_message": "يرجى تحديث تطبيق أساس للمتابعة.",
        "store_url": ANDROID_STORE_URL,
    }
    values.update(overrides)
    return AppUpdatePolicy(**values)


def create_policy(**overrides):
    policy = make_policy(**overrides)
    policy.full_clean()
    policy.save()
    return policy


class AppUpdateCheckApiTests(TestCase):
    url = "/api/v1/mobile/app-update/"

    def setUp(self):
        self.client = APIClient()

    def check(self, platform="android", current_version="1.3.0", current_build=32, **extra):
        params = {}
        if platform is not None:
            params["platform"] = platform
        if current_version is not None:
            params["current_version"] = current_version
        if current_build is not None:
            params["current_build"] = current_build
        return self.client.get(self.url, params, **extra)

    # --- Authentication -------------------------------------------------

    def test_get_works_without_authentication(self):
        create_policy()
        response = self.check()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])

    def test_random_bearer_token_does_not_block_request(self):
        response = self.check(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["meta"]["requester_role"])

    def test_expired_bearer_token_does_not_block_request(self):
        guardian = User.objects.create_user(
            username="guardian",
            email="guardian@example.com",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        refresh = RefreshToken.for_user(guardian)
        refresh["client"] = "mobile"
        refresh["token_version"] = guardian.token_version
        access = refresh.access_token
        access.set_exp(
            from_time=timezone.now() - timedelta(hours=2),
            lifetime=timedelta(minutes=1),
        )
        response = self.check(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["meta"]["requester_role"])

    def test_requester_role_is_null_for_anonymous_user(self):
        response = self.check()
        self.assertEqual(response.data["meta"], {"requester_role": None})

    # --- Decisions ------------------------------------------------------

    def test_missing_policy_fails_open(self):
        response = self.check()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"],
            {
                "platform": "android",
                "check_enabled": False,
                "latest_version": None,
                "latest_build": None,
                "minimum_supported_build": None,
                "update_available": False,
                "force_update": False,
                "update_message": "",
                "store_url": None,
            },
        )

    def test_disabled_policy_returns_both_flags_false(self):
        create_policy(is_check_enabled=False)
        # Build أقل من minimum، ومع ذلك الفحص معطل.
        data = self.check(current_build=1).data["data"]
        self.assertFalse(data["check_enabled"])
        self.assertFalse(data["update_available"])
        self.assertFalse(data["force_update"])
        self.assertEqual(data["latest_build"], 40)
        self.assertEqual(data["minimum_supported_build"], 35)

    def test_current_build_equal_to_latest_has_no_update(self):
        create_policy()
        data = self.check(current_build=40).data["data"]
        self.assertFalse(data["update_available"])
        self.assertFalse(data["force_update"])

    def test_current_build_above_latest_has_no_update(self):
        create_policy()
        data = self.check(current_build=41).data["data"]
        self.assertFalse(data["update_available"])
        self.assertFalse(data["force_update"])

    def test_older_supported_build_gets_optional_update(self):
        create_policy()
        for build in (35, 39):
            data = self.check(current_build=build).data["data"]
            self.assertTrue(data["update_available"], build)
            self.assertFalse(data["force_update"], build)

    def test_build_below_minimum_gets_forced_update(self):
        create_policy()
        data = self.check(current_build=34).data["data"]
        self.assertTrue(data["update_available"])
        self.assertTrue(data["force_update"])

    def test_minimum_equal_to_latest_forces_all_older_builds(self):
        create_policy(minimum_supported_build=40)
        data = self.check(current_build=39).data["data"]
        self.assertTrue(data["force_update"])

    def test_android_and_ios_policies_are_independent(self):
        create_policy(platform="android", latest_build=40, minimum_supported_build=35)
        create_policy(
            platform="ios",
            latest_version="2.0.0",
            latest_build=20,
            minimum_supported_build=10,
            store_url=IOS_STORE_URL,
        )
        android = self.check(platform="android", current_build=30).data["data"]
        ios = self.check(platform="ios", current_build=30).data["data"]
        self.assertTrue(android["force_update"])
        self.assertEqual(android["store_url"], ANDROID_STORE_URL)
        self.assertEqual(ios["platform"], "ios")
        self.assertFalse(ios["update_available"])
        self.assertFalse(ios["force_update"])
        self.assertEqual(ios["latest_version"], "2.0.0")
        self.assertEqual(ios["store_url"], IOS_STORE_URL)

    def test_ios_without_policy_fails_open_even_when_android_exists(self):
        create_policy(minimum_supported_build=40)
        data = self.check(platform="ios", current_build=1).data["data"]
        self.assertEqual(data["platform"], "ios")
        self.assertFalse(data["check_enabled"])
        self.assertFalse(data["force_update"])

    def test_decision_uses_build_not_version_name(self):
        create_policy(latest_version="1.10.0", latest_build=110, minimum_supported_build=100)
        # "1.9.0" أصغر نصيًا لكن Build مساوٍ لأحدث Build.
        data = self.check(current_version="1.9.0", current_build=110).data["data"]
        self.assertFalse(data["update_available"])
        # اسم نسخة "أحدث" لا يمنع التحديث الإجباري إذا كان Build قديمًا.
        data = self.check(current_version="9.9.9", current_build=50).data["data"]
        self.assertTrue(data["update_available"])
        self.assertTrue(data["force_update"])

    # --- Input validation -----------------------------------------------

    def assert_validation_error(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn(field, response.data["errors"])

    def test_invalid_platform_is_rejected(self):
        for platform in ("windows", "ANDROID", ""):
            self.assert_validation_error(self.check(platform=platform), "platform")

    def test_missing_platform_is_rejected(self):
        self.assert_validation_error(self.check(platform=None), "platform")

    def test_missing_current_build_is_rejected(self):
        self.assert_validation_error(self.check(current_build=None), "current_build")

    def test_text_current_build_is_rejected(self):
        for value in ("abc", "1.4.0", "32abc"):
            self.assert_validation_error(self.check(current_build=value), "current_build")

    def test_zero_current_build_is_rejected(self):
        self.assert_validation_error(self.check(current_build=0), "current_build")

    def test_negative_current_build_is_rejected(self):
        self.assert_validation_error(self.check(current_build=-5), "current_build")

    def test_missing_or_blank_current_version_is_rejected(self):
        for value in (None, "", "   "):
            self.assert_validation_error(
                self.check(current_version=value), "current_version"
            )

    def test_too_long_current_version_is_rejected(self):
        self.assert_validation_error(
            self.check(current_version="1" * 51), "current_version"
        )

    # --- HTTP methods ---------------------------------------------------

    def test_write_methods_return_405(self):
        for method in ("post", "put", "patch", "delete"):
            response = getattr(self.client, method)(self.url, {}, format="json")
            self.assertEqual(response.status_code, 405, method)
        self.assertEqual(AppUpdatePolicy.objects.count(), 0)

    def test_head_and_options_are_allowed(self):
        head = self.client.head(
            self.url,
            {"platform": "android", "current_version": "1.3.0", "current_build": 32},
        )
        self.assertEqual(head.status_code, 200)
        options = self.client.options(self.url)
        self.assertEqual(options.status_code, 200)
        allowed = {method.strip() for method in options["Allow"].split(",")}
        self.assertEqual(allowed, {"GET", "HEAD", "OPTIONS"})

    # --- Contract -------------------------------------------------------

    def test_response_contract(self):
        create_policy()
        response = self.check(current_build=32)
        self.assertEqual(
            response.data,
            {
                "success": True,
                "code": "MOBILE_APP_UPDATE_CHECKED",
                "message": "تم التحقق من إصدار التطبيق بنجاح.",
                "data": {
                    "platform": "android",
                    "check_enabled": True,
                    "latest_version": "1.4.0",
                    "latest_build": 40,
                    "minimum_supported_build": 35,
                    "update_available": True,
                    "force_update": True,
                    "update_message": "يرجى تحديث تطبيق أساس للمتابعة.",
                    "store_url": ANDROID_STORE_URL,
                },
                "meta": {"requester_role": None},
            },
        )

    def test_cache_control_is_no_store(self):
        create_policy()
        self.assertEqual(self.check()["Cache-Control"], "no-store")
        self.assertEqual(self.check(current_build=0)["Cache-Control"], "no-store")


class AppUpdatePolicyModelTests(TestCase):
    def assert_invalid(self, policy, field):
        with self.assertRaises(ValidationError) as context:
            policy.full_clean()
        self.assertIn(field, context.exception.message_dict)

    def test_minimum_above_latest_is_rejected(self):
        self.assert_invalid(
            make_policy(latest_build=40, minimum_supported_build=41),
            "minimum_supported_build",
        )

    def test_minimum_above_latest_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_policy(latest_build=40, minimum_supported_build=41).save()

    def test_builds_below_one_are_rejected(self):
        self.assert_invalid(make_policy(latest_build=0, minimum_supported_build=0), "latest_build")
        self.assert_invalid(make_policy(minimum_supported_build=0), "minimum_supported_build")

    def test_builds_below_one_are_rejected_by_database(self):
        for overrides in (
            {"latest_build": 0, "minimum_supported_build": 0},
            {"minimum_supported_build": 0},
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                make_policy(**overrides).save()

    def test_only_one_policy_per_platform(self):
        create_policy()
        self.assert_invalid(make_policy(), "platform")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_policy().save()

    def test_android_rejects_non_google_play_urls(self):
        for url in (
            "http://play.google.com/store/apps/details?id=com.assas.app",
            "https://drive.google.com/file/d/abc/view",
            "https://example.com/assas.apk",
            "https://play.google.com/assas.apk",
            "https://play.google.com.evil.com/store/apps/details?id=x",
            "https://apps.apple.com/app/assas/id1234567890",
            "https://apkpure.com/assas/com.assas.app",
        ):
            self.assert_invalid(make_policy(store_url=url), "store_url")

    def test_ios_rejects_non_app_store_urls(self):
        for url in (
            "http://apps.apple.com/app/assas/id1234567890",
            ANDROID_STORE_URL,
            "https://drive.google.com/file/d/abc/view",
            "https://apps.apple.com.evil.com/app/assas/id1",
            "https://testflight.apple.com/join/abc",
        ):
            self.assert_invalid(
                make_policy(platform="ios", store_url=url), "store_url"
            )

    def test_store_url_platform_mismatch_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_policy(store_url="https://drive.google.com/file/d/abc/view").save()

    def test_android_accepts_google_play_url(self):
        policy = make_policy(store_url=ANDROID_STORE_URL)
        policy.full_clean()
        policy.save()
        self.assertEqual(AppUpdatePolicy.objects.get().store_url, ANDROID_STORE_URL)

    def test_ios_accepts_app_store_url(self):
        policy = make_policy(platform="ios", store_url=IOS_STORE_URL)
        policy.full_clean()
        policy.save()
        self.assertEqual(AppUpdatePolicy.objects.get().platform, "ios")


class AppUpdatePolicyAdminTests(TestCase):
    def setUp(self):
        self.model_admin = admin.site._registry[AppUpdatePolicy]
        self.request = RequestFactory().get("/")
        self.request.user = User.objects.create_superuser(
            username="root",
            email="root@example.com",
            password="StrongPass!493",
        )

    def test_platform_readonly_only_when_editing(self):
        self.assertNotIn(
            "platform", self.model_admin.get_readonly_fields(self.request)
        )
        policy = create_policy()
        readonly = self.model_admin.get_readonly_fields(self.request, policy)
        for field in ("id", "created_at", "updated_at", "platform"):
            self.assertIn(field, readonly)

    def test_delete_is_disabled(self):
        policy = create_policy()
        self.assertFalse(self.model_admin.has_delete_permission(self.request))
        self.assertFalse(self.model_admin.has_delete_permission(self.request, policy))

    def test_admin_form_runs_model_validation(self):
        form_class = self.model_admin.get_form(self.request)
        form = form_class(
            data={
                "platform": "android",
                "is_check_enabled": "on",
                "latest_version": "1.4.0",
                "latest_build": 40,
                "minimum_supported_build": 41,
                "update_message": "",
                "store_url": "https://drive.google.com/file/d/abc/view",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("minimum_supported_build", form.errors)
        self.assertIn("store_url", form.errors)
