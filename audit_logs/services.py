from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from django.db.models import Model

from .models import AuditLog


SENSITIVE_PARTS = {
    "password", "temporary_password", "token", "jwt", "csrf", "cookie",
    "secret", "authorization", "credential",
}


def is_sensitive(name):
    normalized = str(name).lower()
    return any(part in normalized for part in SENSITIVE_PARTS)


def json_safe(value):
    if isinstance(value, Model):
        return str(value.pk)
    if isinstance(value, (UUID, date, datetime, Decimal, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
            if not is_sensitive(key)
        }
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def safe_snapshot(instance):
    snapshot = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key or is_sensitive(field.name):
            continue
        snapshot[field.name] = json_safe(getattr(instance, field.name))
    return snapshot


def changed_fields(instance, validated_data):
    changes = {}
    for field, after in validated_data.items():
        if is_sensitive(field) or not hasattr(instance, field):
            continue
        before = getattr(instance, field)
        before_value, after_value = json_safe(before), json_safe(after)
        if before_value != after_value:
            changes[field] = {"before": before_value, "after": after_value}
    return changes


def log_event(*, actor, action, instance, changes=None, resource_display=None):
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        resource_type=instance._meta.label,
        resource_id=str(instance.pk),
        resource_display=(resource_display or str(instance))[:255],
        changes=json_safe(changes or {}),
    )
