import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from audit_logs.models import AuditLog
from audit_logs.services import get_actor_display, record_audit_event
from accounts.permission_catalog import (
    ALL_MANAGEABLE_PERMISSIONS,
    direct_business_permission_codes,
)


TEMPORARY_PASSWORD_TTL = timedelta(days=20)


def apply_default_role_permissions(user):
    from accounts.role_permission_templates import ROLE_PERMISSION_TEMPLATES

    if user.is_superuser:
        return
    if not user.role or user.role not in ROLE_PERMISSION_TEMPLATES:
        raise ValueError("A valid role is required to apply default permissions.")

    permission_codes = ROLE_PERMISSION_TEMPLATES[user.role]
    query = Q()
    for permission_code in permission_codes:
        app_label, codename = permission_code.split(".", 1)
        query |= Q(
            content_type__app_label=app_label,
            codename=codename,
        )

    permissions = (
        list(Permission.objects.filter(query).select_related("content_type"))
        if permission_codes
        else []
    )
    resolved_codes = {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in permissions
    }
    missing_codes = permission_codes - resolved_codes
    if missing_codes:
        raise ImproperlyConfigured(
            "Role template permissions are missing from Django: "
            f"{sorted(missing_codes)}"
        )

    user.user_permissions.set(permissions)


def _permissions_for_role(role):
    from accounts.role_permission_templates import ROLE_PERMISSION_TEMPLATES

    if role not in ROLE_PERMISSION_TEMPLATES:
        raise ValueError("A valid role is required to apply role permissions.")
    permission_codes = ROLE_PERMISSION_TEMPLATES[role]
    query = Q()
    for permission_code in permission_codes:
        app_label, codename = permission_code.split(".", 1)
        query |= Q(content_type__app_label=app_label, codename=codename)
    permissions = list(Permission.objects.filter(query)) if permission_codes else []
    resolved = {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in permissions
    }
    missing = permission_codes - resolved
    if missing:
        raise ImproperlyConfigured(
            "Role template permissions are missing from Django: "
            f"{sorted(missing)}"
        )
    return permissions


@transaction.atomic
def change_user_role(*, target, new_role, actor, supervisor_scope=None):
    from academics.models import SupervisorScope
    from academics.supervisor_scope_services import set_supervisor_scope

    User = get_user_model()
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("غير مصرح لك بتغيير دور المستخدم.")
    if not (actor.is_superuser or actor.role == User.Role.SCHOOL_ADMIN):
        raise PermissionDenied("فقط إدارة المدرسة تستطيع تغيير أدوار المستخدمين.")
    if new_role not in User.Role.values:
        raise ValueError("A valid role is required.")

    locked = User.objects.select_for_update().get(pk=target.pk)
    if locked.is_superuser:
        raise PermissionDenied("لا يمكن تغيير دور المدير العام المباشر.")
    if locked.role == new_role:
        return locked, False
    if new_role == User.Role.SUPERVISOR and supervisor_scope is None:
        raise ValueError("Supervisor scope is required when changing to supervisor.")

    old_role = locked.role
    before_permissions = direct_business_permission_codes(locked)
    direct_permissions = list(
        locked.user_permissions.select_related("content_type")
    )
    unmanaged_permissions = [
        permission
        for permission in direct_permissions
        if f"{permission.content_type.app_label}.{permission.codename}"
        not in ALL_MANAGEABLE_PERMISSIONS
    ]

    locked.role = new_role
    locked.save(update_fields=["role"])
    locked.user_permissions.set(
        [*unmanaged_permissions, *_permissions_for_role(new_role)]
    )

    if old_role == User.Role.SUPERVISOR and new_role != User.Role.SUPERVISOR:
        SupervisorScope.objects.filter(supervisor=locked).delete()
    if new_role == User.Role.SUPERVISOR:
        set_supervisor_scope(
            supervisor=locked,
            scope_type=supervisor_scope["scope_type"],
            stages=supervisor_scope["stages"],
            actor=actor,
        )

    increment_token_version(locked)
    after_permissions = direct_business_permission_codes(locked)
    record_audit_event(
        actor=actor,
        module=AuditLog.Module.ACCOUNTS,
        action=AuditLog.Action.CHANGE_ROLE,
        message=(
            f"غيّر {get_actor_display(actor)} دور المستخدم "
            f"{get_actor_display(locked)}."
        ),
        target=locked,
        metadata={
            "old_role": old_role,
            "new_role": new_role,
            "before_permissions": before_permissions,
            "after_permissions": after_permissions,
        },
    )
    return locked, True


@transaction.atomic
def replace_user_business_permissions(
    *,
    target_user_id,
    permission_codes,
    permission_objects,
    actor,
    ip_address=None,
):
    User = get_user_model()
    active_admin_ids = list(
        User.objects.select_for_update()
        .filter(
            role=User.Role.SCHOOL_ADMIN,
            is_active=True,
            is_superuser=False,
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    try:
        target = User.objects.select_for_update().get(pk=target_user_id)
    except User.DoesNotExist as exc:
        raise NotFound(
            {
                "code": "USER_NOT_FOUND",
                "detail": "المستخدم المطلوب غير موجود.",
            }
        ) from exc

    if target.pk == actor.pk:
        raise PermissionDenied(
            {
                "code": "USER_PERMISSION_SELF_EDIT_FORBIDDEN",
                "detail": "لا يمكنك تعديل صلاحيات حسابك بنفسك.",
            }
        )
    if target.is_superuser:
        raise PermissionDenied(
            {
                "code": "SUPERUSER_PERMISSION_MANAGEMENT_FORBIDDEN",
                "detail": "لا يمكن إدارة صلاحيات المدير العام المباشرة.",
            }
        )

    before_permissions = direct_business_permission_codes(target)
    before_set = set(before_permissions)
    after_set = set(permission_codes)
    manager_permission = "accounts.manage_user_permissions"

    removes_last_manager = (
        target.is_active
        and target.role == User.Role.SCHOOL_ADMIN
        and manager_permission in before_set
        and manager_permission not in after_set
    )
    if removes_last_manager:
        another_manager_exists = User.objects.filter(
            pk__in=active_admin_ids,
            user_permissions__content_type__app_label="accounts",
            user_permissions__codename="manage_user_permissions",
        ).exclude(pk=target.pk).exists()
        if not another_manager_exists:
            raise PermissionDenied(
                {
                    "code": "LAST_PERMISSION_MANAGER_REQUIRED",
                    "detail": "لا يمكن إزالة صلاحية إدارة المستخدمين من آخر مدير مدرسة فعّال يملكها.",
                }
            )

    added_permissions = sorted(after_set - before_set)
    removed_permissions = sorted(before_set - after_set)
    if not added_permissions and not removed_permissions:
        return target, False

    direct_permissions = list(
        target.user_permissions.select_related("content_type")
    )
    unmanaged_permissions = [
        permission
        for permission in direct_permissions
        if (
            f"{permission.content_type.app_label}.{permission.codename}"
            not in ALL_MANAGEABLE_PERMISSIONS
        )
    ]
    target.user_permissions.set([*unmanaged_permissions, *permission_objects])

    after_permissions = direct_business_permission_codes(target)
    record_audit_event(
        actor=actor,
        module=AuditLog.Module.ACCOUNTS,
        action=AuditLog.Action.UPDATE,
        message=(
            f"عدّل {get_actor_display(actor)} صلاحيات المستخدم "
            f"{get_actor_display(target)}."
        ),
        target=target,
        metadata={
            "before_permissions": before_permissions,
            "after_permissions": after_permissions,
            "added_permissions": added_permissions,
            "removed_permissions": removed_permissions,
        },
        ip_address=ip_address,
    )
    return target, True


def generate_temporary_password():
    return f"{secrets.randbelow(100_000_000):08d}"


def assign_temporary_password(user, *, raw_password=None):
    if raw_password is None:
        password = generate_temporary_password()
    else:
        password = str(raw_password)
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
def set_account_active(user, is_active, *, actor=None):
    locked_user = type(user).objects.select_for_update().get(pk=user.pk)
    if actor is not None:
        from accounts.policies import can_set_account_active

        if not can_set_account_active(actor, locked_user):
            raise PermissionDenied(
                {
                    "code": "SET_ACTIVE_FORBIDDEN",
                    "detail": "ليس لديك صلاحية لتغيير حالة هذا الحساب.",
                }
            )
    if locked_user.is_active == is_active:
        return locked_user, False

    locked_user.is_active = is_active
    locked_user.save(update_fields=["is_active"])
    if not is_active:
        increment_token_version(locked_user)
    if actor is not None:
        action = AuditLog.Action.ACTIVATE if is_active else AuditLog.Action.DEACTIVATE
        record_audit_event(
            actor=actor, module=AuditLog.Module.ACCOUNTS, action=action,
            message=f"{'فعّل' if is_active else 'عطّل'} {get_actor_display(actor)} حساب المستخدم {locked_user}.",
            target=locked_user,
            metadata={"is_active": {"before": not is_active, "after": is_active}},
        )
    return locked_user, True


@transaction.atomic
def reset_account_password(user, *, actor=None):
    locked_user = type(user).objects.select_for_update().get(pk=user.pk)
    if actor is not None:
        from accounts.policies import can_reset_account_password

        if not can_reset_account_password(actor, locked_user):
            raise PermissionDenied(
                {
                    "code": "PASSWORD_RESET_FORBIDDEN",
                    "detail": "ليس لديك صلاحية لإعادة تعيين كلمة مرور هذا الحساب.",
                }
            )
    password = assign_temporary_password(locked_user)
    locked_user.save(
        update_fields=[
            "password",
            "must_change_password",
            "temporary_password_expires_at",
        ]
    )
    increment_token_version(locked_user)
    if actor is not None:
        record_audit_event(
            actor=actor, module=AuditLog.Module.ACCOUNTS,
            action=AuditLog.Action.RESET_PASSWORD,
            message=f"أعاد {get_actor_display(actor)} تعيين كلمة مرور المستخدم {locked_user}.",
            target=locked_user, metadata={},
        )
    return locked_user, password


@transaction.atomic
def delete_guardian_account(user, *, request=None):
    """
    Close a guardian's account at their own request.

    The row is kept because school records point to it with PROTECT. The
    account is deactivated, signed out everywhere and stripped of personal
    data; student records are left untouched. This cannot be undone.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    from audit_logs.services import get_request_ip
    from notifications.models import Notification, PushDevice
    from students.models import GuardianStudent, StudentImportRow

    User = get_user_model()
    locked = User.objects.select_for_update().get(pk=user.pk)
    if locked.role != User.Role.GUARDIAN:
        raise ValueError("Only guardian accounts can be deleted this way.")

    increment_token_version(locked)
    BlacklistedToken.objects.bulk_create(
        [
            BlacklistedToken(token=token)
            for token in OutstandingToken.objects.filter(
                user=locked, blacklistedtoken__isnull=True
            )
        ],
        ignore_conflicts=True,
    )

    locked.is_active = False
    locked.set_unusable_password()
    locked.username = f"deleted-{uuid.uuid4()}"
    locked.first_name = ""
    locked.last_name = ""
    locked.email = None
    locked.phone_number = ""
    locked.national_id = None
    locked.must_change_password = False
    locked.temporary_password_expires_at = None
    locked.save(
        update_fields=[
            "is_active",
            "password",
            "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "national_id",
            "must_change_password",
            "temporary_password_expires_at",
        ]
    )
    locked.user_permissions.clear()
    locked.groups.clear()

    PushDevice.objects.filter(user=locked).delete()
    Notification.objects.filter(recipient=locked).delete()
    GuardianStudent.objects.filter(guardian=locked, is_active=True).update(
        is_active=False,
        updated_at=timezone.now(),
    )
    # Import rows keep the guardian's national id, name and phone in their
    # normalized copy of the spreadsheet; the row itself stays for the school.
    import_rows = StudentImportRow.objects.select_for_update().filter(
        guardian=locked,
        normalized_data__has_key="guardian",
    )
    for row in import_rows:
        row.normalized_data = {
            key: value
            for key, value in row.normalized_data.items()
            if key != "guardian"
        }
        row.save(update_fields=["normalized_data", "updated_at"])

    # Recorded after anonymization so the entry carries the id only.
    record_audit_event(
        actor=locked,
        module=AuditLog.Module.ACCOUNTS,
        action=AuditLog.Action.DELETE,
        message="حذف ولي أمر حسابه من تطبيق الموبايل.",
        target_type=locked._meta.label,
        target_id=locked.pk,
        target_display=str(locked.pk),
        ip_address=get_request_ip(request),
    )
    return locked
