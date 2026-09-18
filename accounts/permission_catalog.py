from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BusinessPermission:
    code: str
    label: str
    module: str


def _permission(code, label):
    module = code.partition(".")[0]
    return BusinessPermission(code=code, label=label, module=module)


# Explicit, deliberately curated allowlist. Django's complete Permission table is
# not a business-permission catalog.
PERMISSION_CATALOG = tuple(
    _permission(code, label)
    for code, label in (
        ("academics.add_academicyear", "إضافة سنة دراسية"),
        ("academics.change_academicyear", "تعديل سنة دراسية"),
        ("academics.delete_academicyear", "حذف سنة دراسية"),
        ("academics.view_academicyear", "عرض السنوات الدراسية"),
        ("academics.add_gradelevel", "إضافة صف دراسي"),
        ("academics.change_gradelevel", "تعديل صف دراسي"),
        ("academics.delete_gradelevel", "حذف صف دراسي"),
        ("academics.view_gradelevel", "عرض الصفوف الدراسية"),
        ("academics.add_gradesubject", "إضافة مادة إلى صف"),
        ("academics.change_gradesubject", "تعديل مادة الصف"),
        ("academics.delete_gradesubject", "حذف مادة من صف"),
        ("academics.view_gradesubject", "عرض مواد الصفوف"),
        ("academics.add_section", "إضافة شعبة"),
        ("academics.change_section", "تعديل شعبة"),
        ("academics.delete_section", "حذف شعبة"),
        ("academics.view_section", "عرض الشعب"),
        ("academics.add_subject", "إضافة مادة"),
        ("academics.change_subject", "تعديل مادة"),
        ("academics.delete_subject", "حذف مادة"),
        ("academics.view_subject", "عرض المواد"),
        ("academics.add_term", "إضافة فصل دراسي"),
        ("academics.change_term", "تعديل فصل دراسي"),
        ("academics.delete_term", "حذف فصل دراسي"),
        ("academics.view_term", "عرض الفصول الدراسية"),
        ("accounts.add_user", "إضافة مستخدم"),
        ("accounts.change_user", "تعديل مستخدم"),
        ("accounts.manage_user_permissions", "إدارة صلاحيات المستخدمين"),
        ("accounts.reset_user_password", "إعادة تعيين كلمة مرور المستخدم"),
        ("accounts.set_user_active", "تغيير حالة حساب المستخدم"),
        ("accounts.view_user", "عرض المستخدمين"),
        ("announcements.add_announcement", "إضافة إعلان"),
        ("announcements.change_announcement", "تعديل إعلان"),
        ("announcements.delete_announcement", "حذف إعلان"),
        ("announcements.view_announcement", "عرض الإعلانات"),
        ("appointments.decide_appointment_request", "اتخاذ قرار بشأن طلب موعد"),
        ("appointments.view_appointmentrequest", "عرض طلبات المواعيد"),
        ("audit_logs.view_auditlog", "عرض سجل النشاطات"),
        ("attendance.add_attendancesheet", "إنشاء سجل حضور"),
        ("attendance.change_attendancerecord", "تعديل حالة حضور طالب"),
        ("attendance.change_attendancesheet", "تعديل سجل حضور"),
        ("attendance.view_attendancerecord", "عرض حالات حضور الطلاب"),
        ("attendance.view_attendancesheet", "عرض سجلات الحضور"),
        ("behavior.add_behaviornote", "إضافة ملاحظة سلوكية"),
        ("behavior.change_behaviornote", "تعديل ملاحظة سلوكية"),
        ("behavior.delete_behaviornote", "حذف ملاحظة سلوكية"),
        ("behavior.view_behaviornote", "عرض الملاحظات السلوكية"),
        ("finance.add_gradetuitionplan", "إضافة خطة رسوم"),
        ("finance.add_payment", "تسجيل دفعة"),
        ("finance.add_studentdiscount", "إضافة حسم"),
        ("finance.cancel_discount", "إلغاء حسم"),
        ("finance.cancel_payment", "إلغاء دفعة"),
        ("finance.change_gradetuitionplan", "تعديل خطة رسوم"),
        ("finance.view_gradetuitionplan", "عرض خطط الرسوم"),
        ("finance.view_payment", "عرض الدفعات"),
        ("finance.view_studentdiscount", "عرض الحسومات"),
        ("finance.view_studentfinancialaccount", "عرض الحسابات المالية للطلاب"),
        ("grades.add_assessment", "إضافة تقييم"),
        ("grades.change_assessment", "تعديل تقييم"),
        ("grades.change_studentscore", "تعديل علامة طالب"),
        ("grades.create_grade_wide_assessment", "إنشاء تقييم لجميع شعب الصف"),
        ("grades.delete_assessment", "حذف تقييم"),
        ("grades.publish_grades", "نشر العلامات"),
        ("grades.view_assessment", "عرض التقييمات"),
        ("grades.view_studentscore", "عرض علامات الطلاب"),
        ("homework.add_homework", "إضافة واجب"),
        ("homework.change_homework", "تعديل واجب"),
        ("homework.delete_homework", "حذف واجب"),
        ("homework.view_homework", "عرض الواجبات"),
        ("school_requests.reply_to_request", "الرد على طلب مدرسي"),
        ("school_requests.view_schoolrequest", "عرض الطلبات المدرسية"),
        ("students.add_enrollment", "إضافة تسجيل دراسي"),
        ("students.add_guardianstudent", "ربط ولي أمر بطالب"),
        ("students.add_student", "إضافة طالب"),
        ("students.change_enrollment", "تعديل تسجيل دراسي"),
        ("students.change_student", "تعديل طالب"),
        ("students.change_studenthealthprofile", "تعديل الملف الصحي للطالب"),
        ("students.delete_enrollment", "حذف تسجيل دراسي"),
        ("students.delete_guardianstudent", "حذف ارتباط ولي أمر بطالب"),
        ("students.delete_student", "حذف طالب"),
        ("students.register_student", "تسجيل طالب"),
        ("students.transfer_student", "نقل طالب بين الشعب"),
        ("students.view_enrollment", "عرض التسجيلات الدراسية"),
        ("students.view_guardianstudent", "عرض ارتباطات أولياء الأمور"),
        ("students.view_student", "عرض الطلاب"),
        ("students.view_student_profile", "عرض الملف الشامل للطالب"),
        ("students.view_studenthealthprofile", "عرض الملف الصحي للطالب"),
        ("teaching.add_teacherassignment", "إضافة إسناد تعليمي"),
        ("teaching.change_teacherassignment", "تعديل إسناد تعليمي"),
        ("teaching.delete_teacherassignment", "حذف إسناد تعليمي"),
        ("teaching.view_teacherassignment", "عرض الإسنادات التعليمية"),
    )
)

ALL_MANAGEABLE_PERMISSIONS = frozenset(
    permission.code for permission in PERMISSION_CATALOG
)


MODULE_LABELS = {
    "accounts": "الحسابات",
    "academics": "الشؤون الأكاديمية",
    "students": "الطلاب",
    "teaching": "الإسنادات التعليمية",
    "attendance": "الحضور",
    "behavior": "السلوك",
    "homework": "الواجبات",
    "announcements": "الإعلانات",
    "grades": "العلامات",
    "school_requests": "الطلبات",
    "appointments": "المواعيد",
    "finance": "المالية",
    "audit_logs": "سجل النشاطات",
}


def direct_business_permission_codes(user):
    direct_codes = {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in user.user_permissions.select_related("content_type")
    }
    return [
        permission.code
        for permission in PERMISSION_CATALOG
        if permission.code in direct_codes
    ]


def effective_business_permission_codes(user):
    if user.is_superuser:
        return [permission.code for permission in PERMISSION_CATALOG]
    return direct_business_permission_codes(user)


def catalog_modules():
    permissions_by_module = {module: [] for module in MODULE_LABELS}
    for permission in PERMISSION_CATALOG:
        permissions_by_module[permission.module].append(
            {"code": permission.code, "label": permission.label}
        )

    return [
        {
            "module": module,
            "label": label,
            "permissions": permissions_by_module[module],
        }
        for module, label in MODULE_LABELS.items()
        if permissions_by_module[module]
    ]
