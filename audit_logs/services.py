from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from django.db.models import Model

from .models import AuditLog


SENSITIVE_PARTS = {
    "password", "temporary_password", "token", "access_token", "refresh",
    "refresh_token", "jwt", "csrf", "cookie", "authorization", "secret",
    "credential",
}


def is_sensitive(name):
    normalized = str(name).casefold()
    return any(part in normalized for part in SENSITIVE_PARTS)


def sanitize_metadata(value):
    if isinstance(value, Model):
        return str(value.pk)
    if isinstance(value, Enum):
        return sanitize_metadata(value.value)
    if isinstance(value, (UUID, date, datetime, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): sanitize_metadata(item)
            for key, item in value.items()
            if not is_sensitive(key)
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_metadata(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


json_safe = sanitize_metadata


def safe_snapshot(instance):
    return {
        field.name: sanitize_metadata(getattr(instance, field.name))
        for field in instance._meta.concrete_fields
        if not field.primary_key and not is_sensitive(field.name)
    }


def changed_fields(instance, validated_data):
    changes = {}
    for field, after in validated_data.items():
        if is_sensitive(field) or not hasattr(instance, field):
            continue
        before_value = sanitize_metadata(getattr(instance, field))
        after_value = sanitize_metadata(after)
        if before_value != after_value:
            changes[field] = {"before": before_value, "after": after_value}
    return changes


def get_actor_display(actor):
    if actor is None:
        return "مستخدم سابق"
    full_name = actor.get_full_name().strip() if hasattr(actor, "get_full_name") else ""
    return full_name or getattr(actor, "username", "") or str(actor)


def get_request_ip(request):
    return request.META.get("REMOTE_ADDR") if request is not None else None


def record_audit_event(
    *, actor, module, action, message, target=None, target_type=None,
    target_id=None, target_display=None, metadata=None, ip_address=None,
):
    if target is not None:
        target_type = target_type or target._meta.label
        target_id = target_id if target_id is not None else target.pk
        target_display = target_display or str(target)
    if not target_type or target_id is None:
        raise ValueError("target أو target_type وtarget_id مطلوبان.")
    return AuditLog.objects.create(
        actor=actor,
        actor_display=get_actor_display(actor)[:255],
        module=module,
        action=action,
        message=message,
        target_type=str(target_type)[:100],
        target_id=str(target_id)[:255],
        target_display=(target_display or str(target_id))[:255],
        metadata=sanitize_metadata(metadata or {}),
        ip_address=ip_address,
    )


def log_event(*, actor, action, instance, changes=None, resource_display=None, module=None, message=None):
    """Compatibility wrapper; approved call sites should provide business context."""
    inferred = instance._meta.app_label
    if inferred == "teaching":
        inferred = AuditLog.Module.ACADEMICS
    if inferred not in AuditLog.Module.values:
        inferred = AuditLog.Module.OTHER
    return record_audit_event(
        actor=actor,
        module=module or inferred,
        action=action,
        message=message or f"{AuditLog.Action(action).label} - {resource_display or instance}",
        target=instance,
        target_display=resource_display,
        metadata=changes,
    )
