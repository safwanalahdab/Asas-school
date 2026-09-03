from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User

from .models import PushDevice


@transaction.atomic
def register_push_device(
    *, user, installation_id, fcm_token, platform, device_name=""
):
    # Locking the guardian serializes limit enforcement for concurrent registrations.
    User.objects.select_for_update().get(pk=user.pk)
    now = timezone.now()
    device, created = PushDevice.objects.select_for_update().get_or_create(
        installation_id=installation_id,
        defaults={
            "user": user,
            "fcm_token": f"pending:{installation_id}",
            "platform": platform,
            "device_name": device_name,
            "is_active": False,
            "last_seen_at": now,
        },
    )

    # Token rotation may replace another installation owned by the same guardian,
    # but client input must never deactivate another guardian's device.
    token_conflicts = PushDevice.objects.select_for_update().filter(
        fcm_token=fcm_token,
        is_active=True,
    ).exclude(pk=device.pk)
    if token_conflicts.exclude(user=user).exists():
        raise ValidationError({"fcm_token": "FCM token is already registered."})
    token_conflicts.update(is_active=False, updated_at=now)

    device.user = user
    device.fcm_token = fcm_token
    device.platform = platform
    device.device_name = device_name
    device.is_active = True
    device.last_seen_at = now
    device.full_clean(validate_unique=False, validate_constraints=False)
    try:
        with transaction.atomic():
            device.save()
    except IntegrityError as error:
        if PushDevice.objects.filter(
            fcm_token=fcm_token,
            is_active=True,
        ).exclude(pk=device.pk).exists():
            raise ValidationError(
                {"fcm_token": "FCM token is already registered."}
            ) from error
        raise

    limit = settings.MOBILE_MAX_ACTIVE_DEVICES_PER_GUARDIAN
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValidationError(
            "MOBILE_MAX_ACTIVE_DEVICES_PER_GUARDIAN must be a positive integer."
        )
    active_devices = PushDevice.objects.filter(user=user, is_active=True)
    excess_count = max(0, active_devices.count() - limit)
    excess_ids = list(
        PushDevice.objects.select_for_update()
        .filter(user=user, is_active=True)
        .exclude(pk=device.pk)
        .order_by("last_seen_at", "created_at", "id")
        .values_list("pk", flat=True)[:excess_count]
    )
    if excess_ids:
        PushDevice.objects.filter(pk__in=excess_ids).update(
            is_active=False,
            updated_at=now,
        )
    return device, created


@transaction.atomic
def unregister_push_device(*, user, installation_id):
    device = (
        PushDevice.objects.select_for_update()
        .filter(user=user, installation_id=installation_id)
        .first()
    )
    if device is not None and device.is_active:
        device.is_active = False
        device.save(update_fields=["is_active", "updated_at"])
    return device
