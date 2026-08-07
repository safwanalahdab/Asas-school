from django.contrib.auth import get_user_model


User = get_user_model()


WEB_DASHBOARD_ROLES = {
    User.Role.SCHOOL_ADMIN,
    User.Role.SECRETARIAT,
    User.Role.SUPERVISOR,
    User.Role.TEACHER,
    User.Role.TECH_SUPPORT,
}

ACCOUNT_CREATORS = {
    User.Role.SCHOOL_ADMIN,
    User.Role.SECRETARIAT,
    User.Role.SUPERVISOR,
}

CREATABLE_ROLES = {
    User.Role.SCHOOL_ADMIN,
    User.Role.SECRETARIAT,
    User.Role.SUPERVISOR,
    User.Role.TEACHER,
    User.Role.GUARDIAN,
    User.Role.TECH_SUPPORT,
}

ROLE_CREATION_MATRIX = {
    User.Role.SECRETARIAT: {User.Role.GUARDIAN, User.Role.SUPERVISOR},
    User.Role.SUPERVISOR: {User.Role.GUARDIAN},
}


def can_create_accounts(user):
    return bool(user and user.is_authenticated and user.is_active and (
        user.is_superuser or user.role in ACCOUNT_CREATORS
    ))


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

def can_view_accounts(user):
    """
    يحدد هل يستطيع المستخدم فتح واجهة قائمة الحسابات.

    الحسابات التي ستظهر له فعليًا يتم تحديدها
    لاحقًا داخل QuerySet بناءً على دوره.
    """

    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (
            user.is_superuser
            or user.role in {
                User.Role.SCHOOL_ADMIN,
                User.Role.SECRETARIAT,
                User.Role.SUPERVISOR,
            }
        )
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
        ).exclude(
            role=User.Role.SCHOOL_ADMIN,
        )

    if user.role == User.Role.SUPERVISOR:
        return queryset.filter(
            is_superuser=False,
            role=User.Role.GUARDIAN,
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
    return False


def can_update_account(actor, target, new_role=None):
    if not can_manage_account(actor, target):
        return False
    return new_role is None or can_create_role(actor, new_role)


def can_set_account_active(actor, target):
    return bool(actor.pk != target.pk and can_manage_account(actor, target))


def can_reset_account_password(actor, target):
    return can_manage_account(actor, target)
