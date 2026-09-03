import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from notifications.device_services import register_push_device, unregister_push_device
from notifications.models import PushDevice
from notifications.throttles import (
    MobileDeviceRegistrationThrottle,
    MobileDeviceUnregistrationThrottle,
)


User = get_user_model()


class PushDeviceServiceTests(TestCase):
    def setUp(self):
        self.guardian = self.make_user("device-guardian")
        self.other = self.make_user("device-other")

    def make_user(self, username, role=User.Role.GUARDIAN, **overrides):
        values = {
            "username": username,
            "password": "StrongPass!493",
            "role": role,
            "must_change_password": False,
        }
        values.update(overrides)
        return User.objects.create_user(**values)

    def register(self, **overrides):
        values = {
            "user": self.guardian,
            "installation_id": uuid.uuid4(),
            "fcm_token": f"token-{uuid.uuid4()}",
            "platform": PushDevice.Platform.ANDROID,
            "device_name": " Phone ",
        }
        values.update(overrides)
        return register_push_device(**values)

    def test_model_contract_and_platform_validation(self):
        device, created = self.register()
        self.assertTrue(created)
        self.assertEqual(device.device_name, "Phone")
        self.assertTrue(device.is_active)
        self.assertIsNotNone(device.last_seen_at)
        for platform in PushDevice.Platform.values:
            candidate = PushDevice(
                user=self.guardian,
                installation_id=uuid.uuid4(),
                fcm_token=f"token-{platform}",
                platform=platform,
                last_seen_at=timezone.now(),
            )
            candidate.full_clean()
        with self.assertRaises(ValidationError):
            PushDevice(
                user=self.guardian,
                installation_id=uuid.uuid4(),
                fcm_token="token-invalid",
                platform="windows",
                last_seen_at=timezone.now(),
            ).full_clean()

    def test_installation_unique_and_blank_token_rejected(self):
        installation_id = uuid.uuid4()
        self.register(installation_id=installation_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PushDevice.objects.create(
                user=self.guardian,
                installation_id=installation_id,
                fcm_token="another-token",
                platform=PushDevice.Platform.IOS,
                last_seen_at=timezone.now(),
            )
        with self.assertRaises(ValidationError):
            self.register(fcm_token="   ")

    def test_same_installation_is_upserted_and_reactivated(self):
        installation_id = uuid.uuid4()
        first, _ = self.register(installation_id=installation_id)
        old_seen = first.last_seen_at
        first.is_active = False
        first.save(update_fields=["is_active"])
        second, created = self.register(
            installation_id=installation_id,
            fcm_token="rotated-token",
            platform=PushDevice.Platform.IOS,
            device_name="iPhone",
        )
        self.assertFalse(created)
        self.assertEqual(PushDevice.objects.count(), 1)
        self.assertEqual(second.fcm_token, "rotated-token")
        self.assertEqual(second.platform, PushDevice.Platform.IOS)
        self.assertEqual(second.device_name, "iPhone")
        self.assertTrue(second.is_active)
        self.assertGreaterEqual(second.last_seen_at, old_seen)

    def test_installation_transfers_to_authenticated_owner(self):
        installation_id = uuid.uuid4()
        device, _ = self.register(installation_id=installation_id)
        transferred, created = self.register(
            user=self.other,
            installation_id=installation_id,
            fcm_token="other-token",
        )
        self.assertFalse(created)
        self.assertEqual(transferred.pk, device.pk)
        self.assertEqual(transferred.user, self.other)
        self.assertFalse(
            PushDevice.objects.filter(user=self.guardian, pk=device.pk).exists()
        )

    def test_reused_active_token_deactivates_old_device(self):
        old, _ = self.register(fcm_token="shared-token")
        new, _ = self.register(fcm_token="shared-token")
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        self.assertTrue(new.is_active)
        self.assertEqual(
            PushDevice.objects.filter(fcm_token="shared-token", is_active=True).count(),
            1,
        )

    def test_cross_user_token_collision_cannot_deactivate_other_device(self):
        other_device, _ = self.register(
            user=self.other,
            fcm_token="other-guardian-token",
        )

        with self.assertRaises(ValidationError):
            self.register(fcm_token="other-guardian-token")

        other_device.refresh_from_db()
        self.assertTrue(other_device.is_active)
        self.assertEqual(other_device.user, self.other)
        self.assertEqual(PushDevice.objects.count(), 1)

    def test_oldest_device_is_deactivated_at_configured_limit(self):
        devices = []
        for index in range(3):
            device, _ = self.register(device_name=str(index))
            seen = timezone.now() - timedelta(days=3 - index)
            PushDevice.objects.filter(pk=device.pk).update(last_seen_at=seen)
            devices.append(device)
        devices[0].refresh_from_db()
        devices[1].refresh_from_db()
        devices[2].refresh_from_db()
        self.assertFalse(devices[0].is_active)
        self.assertTrue(devices[1].is_active)
        self.assertTrue(devices[2].is_active)
        self.assertEqual(PushDevice.objects.filter(user=self.guardian, is_active=True).count(), 2)

    @override_settings(MOBILE_MAX_ACTIVE_DEVICES_PER_GUARDIAN=1)
    def test_limit_comes_from_settings_and_reregister_keeps_current(self):
        older, _ = self.register()
        newer, _ = self.register()
        older.refresh_from_db()
        self.assertFalse(older.is_active)
        older, _ = self.register(installation_id=older.installation_id)
        newer.refresh_from_db()
        self.assertTrue(older.is_active)
        self.assertFalse(newer.is_active)

    def test_unregister_is_idempotent_scoped_and_preserves_row(self):
        own, _ = self.register()
        foreign, _ = self.register(user=self.other)
        self.assertIsNotNone(unregister_push_device(user=self.guardian, installation_id=own.installation_id))
        self.assertIsNone(unregister_push_device(user=self.guardian, installation_id=foreign.installation_id))
        self.assertIsNone(unregister_push_device(user=self.guardian, installation_id=uuid.uuid4()))
        unregister_push_device(user=self.guardian, installation_id=own.installation_id)
        own.refresh_from_db()
        foreign.refresh_from_db()
        self.assertFalse(own.is_active)
        self.assertTrue(foreign.is_active)
        self.assertEqual(PushDevice.objects.count(), 2)


class PushDeviceApiTests(TestCase):
    register_url = "/api/v1/mobile/devices/"
    unregister_url = "/api/v1/mobile/devices/unregister/"

    def setUp(self):
        self.client = APIClient()
        self.guardian = User.objects.create_user(
            username="api-device-guardian",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.payload = {
            "installation_id": str(uuid.uuid4()),
            "fcm_token": "api-fcm-token",
            "platform": "android",
            "device_name": "Samsung A54",
        }

    def authenticate(self, user=None, client="mobile"):
        user = user or self.guardian
        token = RefreshToken.for_user(user)
        token["client"] = client
        token["token_version"] = user.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def test_authentication_and_guardian_boundaries(self):
        self.assertEqual(self.client.post(self.register_url, self.payload).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.post(self.register_url, self.payload).status_code, 401)
        teacher = User.objects.create_user(username="device-teacher", password="x", role=User.Role.TEACHER, must_change_password=False)
        self.authenticate(teacher)
        self.assertEqual(self.client.post(self.register_url, self.payload).status_code, 403)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        self.assertEqual(self.client.post(self.register_url, self.payload).status_code, 403)

        inactive = User.objects.create_user(
            username="inactive-device-guardian",
            password="x",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.authenticate(inactive)
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        self.assertEqual(self.client.post(self.register_url, self.payload).status_code, 401)

    def test_register_uses_request_user_and_hides_sensitive_fields(self):
        other = User.objects.create_user(username="other-owner", password="x", role=User.Role.GUARDIAN, must_change_password=False)
        self.authenticate()
        response = self.client.post(
            self.register_url,
            {**self.payload, "user": str(other.pk), "user_id": str(other.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        device = PushDevice.objects.get()
        self.assertEqual(device.user, self.guardian)
        self.assertEqual(response.data["code"], "MOBILE_DEVICE_REGISTERED")
        self.assertTrue({"user", "user_id", "username", "fcm_token"}.isdisjoint(response.data["data"]))

    def test_validation_contract(self):
        self.authenticate()
        cases = (
            {**self.payload, "installation_id": "bad"},
            {**self.payload, "platform": "windows"},
            {**self.payload, "fcm_token": "   "},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(self.register_url, payload, format="json").status_code, 400)

    def test_unregister_is_successful_and_idempotent(self):
        self.authenticate()
        self.client.post(self.register_url, self.payload, format="json")
        body = {"installation_id": self.payload["installation_id"]}
        first = self.client.post(self.unregister_url, body, format="json")
        second = self.client.post(self.unregister_url, body, format="json")
        missing = self.client.post(self.unregister_url, {"installation_id": str(uuid.uuid4())}, format="json")
        self.assertEqual((first.status_code, second.status_code, missing.status_code), (200, 200, 200))
        self.assertEqual(first.data["code"], "MOBILE_DEVICE_UNREGISTERED")
        self.assertFalse(PushDevice.objects.get().is_active)

    def test_throttle_configuration(self):
        self.assertEqual(MobileDeviceRegistrationThrottle.scope, "mobile_device_registration")
        self.assertEqual(MobileDeviceUnregistrationThrottle.scope, "mobile_device_unregistration")
