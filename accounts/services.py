import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone


TEMPORARY_PASSWORD_TTL = timedelta(hours=72)


def generate_temporary_password():
    return f"{secrets.randbelow(100_000_000):08d}"


def assign_temporary_password(user):
    password = generate_temporary_password()
    user.set_password(password)
    user.must_change_password = True
    user.temporary_password_expires_at = timezone.now() + TEMPORARY_PASSWORD_TTL
    return password


def temporary_password_is_expired(user):
    expires_at = user.temporary_password_expires_at
    return bool(
        user.must_change_password
        and expires_at is not None
        and expires_at <= timezone.now()
    )


def increment_token_version(user):
    type(user).objects.filter(pk=user.pk).update(
        token_version=F("token_version") + 1,
    )
    user.refresh_from_db(fields=["token_version"])


@transaction.atomic
def set_account_active(user, is_active):
    locked_user = type(user).objects.select_for_update().get(pk=user.pk)
    if locked_user.is_active == is_active:
        return locked_user, False

    locked_user.is_active = is_active
    locked_user.save(update_fields=["is_active"])
    if not is_active:
        increment_token_version(locked_user)
    return locked_user, True


@transaction.atomic
def reset_account_password(user):
    locked_user = type(user).objects.select_for_update().get(pk=user.pk)
    password = assign_temporary_password(locked_user)
    locked_user.save(
        update_fields=[
            "password",
            "must_change_password",
            "temporary_password_expires_at",
        ]
    )
    increment_token_version(locked_user)
    return locked_user, password
