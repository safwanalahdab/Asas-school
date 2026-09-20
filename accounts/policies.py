from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.account_scope import (
    can_edit_teacher_account,
    can_reset_teacher_password,
    can_set_teacher_active,
    teacher_accounts_visible_to_supervisor,
)


User = get_user_model()


WEB_DASHBOARD_ROLES = {
    User.Role.SCHOOL_ADMIN,
    User.Role.SECRETARIAT,
    User.Role.SUPERVISOR,
    User.Role.TEACHER,
    User.Role.ACCOUNTANT,
    User.Role.TECH_SUPPORT,
}

CREATABLE_ROLES = {
    User.Role.SCHOOL_ADMIN,
    User.Role.SECRETARIAT,
    User.Role.SUPERVISOR,
    User.Role.TEACHER,
    User.Role.ACCOUNTANT,
    User.Role.GUARDIAN,
    User.Role.TECH_SUPPORT,
}

ROLE_CREATION_MATRIX = {
    User.Role.SECRETARIAT: {User.Role.TEACHER, User.Role.ACCOUNTANT},
    User.Role.SUPERVISOR: {User.Role.TEACHER, User.Role.GUARDIAN},
}


def can_create_role(actor, target_role):
    if target_role not in CREATABLE_ROLES:
        return False
    if actor.is_superuser or actor.role == User.Role.SCHOOL_ADMIN:
        return True
    return target_role in ROLE_CREATION_MATRIX.get(actor.role, set())


def can_access_web_dashboard(user):
    """
    يسمح بالدخول إلى لوحة الويب في حال:

    1. المستخدم موجود ومسجل دخوله.
    2. الحساب فعال.
    3. المستخدم Superuser،
       أو دوره من أدوار لوحة الويب.
    """

    if (
        not user
        or not user.is_authenticated
        or not user.is_active
    ):
        return False

    return (
        user.is_superuser
        or user.role in WEB_DASHBOARD_ROLES
    )

def get_visible_accounts_queryset(user, queryset):
    """
    يفلتر حسابات المستخدمين حسب دور المستخدم الحالي.

    لا يقرر هل يستطيع فتح الـEndpoint؛
    بل يقرر أي حسابات تظهر له بعد السماح بالدخول.
    """

    if user.is_superuser:
        return queryset

    if user.role == User.Role.SCHOOL_ADMIN:
        return queryset.filter(is_superuser=False)

    if user.role == User.Role.SECRETARIAT:
        return queryset.filter(
            is_superuser=False,
            role__in=[User.Role.TEACHER, User.Role.ACCOUNTANT],
        )

    if user.role == User.Role.SUPERVISOR:
        guardians = Q(is_superuser=False, role=User.Role.GUARDIAN)
        visible_teacher_ids = teacher_accounts_visible_to_supervisor(
            queryset.filter(is_superuser=False, role=User.Role.TEACHER),
            user,
        ).values("pk")
        return queryset.filter(
            guardians | Q(pk__in=visible_teacher_ids)
        )

    return queryset.none()


def can_manage_account(actor, target):
    if not actor or not actor.is_authenticated or not actor.is_active:
        return False
    if target.is_superuser:
        return False
    if actor.is_superuser or actor.role == User.Role.SCHOOL_ADMIN:
        return True
    if actor.role == User.Role.SECRETARIAT:
        return can_create_role(actor, target.role)
    if actor.role == User.Role.SUPERVISOR:
        if target.role == User.Role.GUARDIAN:
            return True
        if target.role == User.Role.TEACHER:
            return can_edit_teacher_account(actor, target)
    return False


def can_update_account(actor, target, new_role=None):
    if not can_manage_account(actor, target):
        return False
    return new_role is None or can_create_role(actor, new_role)


def can_change_account_role(actor, target):
    return bool(
        actor
        and actor.is_authenticated
        and actor.is_active
        and not target.is_superuser
        and (actor.is_superuser or actor.role == User.Role.SCHOOL_ADMIN)
    )


def can_set_account_active(actor, target):
    if actor.pk == target.pk:
        return False
    if actor.role == User.Role.SUPERVISOR and target.role == User.Role.TEACHER:
        return can_set_teacher_active(actor, target)
    return can_manage_account(actor, target)


def can_reset_account_password(actor, target):
    if actor.role == User.Role.SUPERVISOR and target.role == User.Role.TEACHER:
        return can_reset_teacher_password(actor, target)
    return can_manage_account(actor, target)
