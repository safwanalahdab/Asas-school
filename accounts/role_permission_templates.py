from accounts.models import User
from accounts.permission_catalog import ALL_MANAGEABLE_PERMISSIONS


def _permissions_for_modules(*modules):
    prefixes = tuple(f"{module}." for module in modules)
    return {
        code
        for code in ALL_MANAGEABLE_PERMISSIONS
        if code.startswith(prefixes)
    }


_SECRETARIAT_PERMISSIONS = _permissions_for_modules(
    "academics",
    "announcements",
    "school_requests",
    "students",
    "teaching",
) - {
    "students.correct_enrollment_placement",
} | {
    "accounts.add_user",
    "accounts.change_user",
    "accounts.reset_user_password",
    "accounts.set_user_active",
    "accounts.view_user",
    "appointments.view_appointmentrequest",
    "finance.add_payment",
    "finance.view_payment",
    "finance.view_studentfinancialaccount",
}

_SUPERVISOR_PERMISSIONS = _permissions_for_modules(
    "academics",
    "announcements",
    "attendance",
    "behavior",
    "grades",
    "homework",
    "school_requests",
    "students",
    "teaching",
) | {
    "accounts.add_user",
    "accounts.change_user",
    "accounts.reset_user_password",
    "accounts.set_user_active",
    "accounts.view_user",
}

_TEACHER_PERMISSIONS = {
    "announcements.view_announcement",
    "grades.add_assessment",
    "grades.change_assessment",
    "grades.change_studentscore",
    "grades.delete_assessment",
    "grades.view_assessment",
    "grades.view_studentscore",
    "homework.add_homework",
    "homework.change_homework",
    "homework.delete_homework",
    "homework.view_homework",
    "students.view_enrollment",
    "students.view_student",
    "teaching.view_teacherassignment",
}

_ACCOUNTANT_PERMISSIONS = {
    "finance.view_gradetuitionplan",
    "finance.view_studentfinancialaccount",
    "finance.view_payment",
    "finance.add_payment",
    "finance.cancel_payment",
    "finance.view_studentdiscount",
    "finance.add_studentdiscount",
    "finance.cancel_discount",
}


ROLE_PERMISSION_TEMPLATES = {
    User.Role.SCHOOL_ADMIN: frozenset(ALL_MANAGEABLE_PERMISSIONS),
    User.Role.SECRETARIAT: frozenset(_SECRETARIAT_PERMISSIONS),
    User.Role.SUPERVISOR: frozenset(_SUPERVISOR_PERMISSIONS),
    User.Role.TEACHER: frozenset(_TEACHER_PERMISSIONS),
    User.Role.ACCOUNTANT: frozenset(_ACCOUNTANT_PERMISSIONS),
    User.Role.GUARDIAN: frozenset(),
    User.Role.TECH_SUPPORT: frozenset(),
}


unknown_template_permissions = set().union(
    *ROLE_PERMISSION_TEMPLATES.values()
) - ALL_MANAGEABLE_PERMISSIONS
if unknown_template_permissions:
    raise RuntimeError(
        "Role templates contain permissions outside the business catalog: "
        f"{sorted(unknown_template_permissions)}"
    )
