from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from academics.models import Section
from accounts.models import User
from students.models import Enrollment
from teaching.models import TeacherAssignment
from .domain import ATTENDANCE_FIELDS, normalize_and_validate_record
from .models import AttendanceRecord, AttendanceSheet


def _teacher_is_assigned(user, section, date):
    return TeacherAssignment.objects.filter(
        teacher=user, section=section, start_date__lte=date,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=date)).exists()


@transaction.atomic
def create_attendance_sheet(*, section, actor, records):
    today = timezone.localdate()
    if today.weekday() in {4, 5}:
        raise ValidationError({"code": "ATTENDANCE_NOT_ALLOWED_ON_WEEKEND", "detail": "لا يمكن تسجيل الحضور يومي الجمعة والسبت."})
    section = Section.objects.select_for_update().get(pk=section.pk)
    if actor.role == User.Role.TEACHER and not actor.is_superuser and not _teacher_is_assigned(actor, section, today):
        raise PermissionDenied({"code": "ATTENDANCE_TEACHER_NOT_ASSIGNED", "detail": "المعلّم غير مكلّف بهذه الشعبة اليوم."})
    if AttendanceSheet.objects.filter(section=section, attendance_date=today).exists():
        raise ValidationError({"code": "ATTENDANCE_SHEET_ALREADY_EXISTS", "detail": "تم أخذ حضور هذه الشعبة مسبقًا لهذا اليوم."})

    roster = list(Enrollment.objects.select_related("student").filter(
        section=section, student__is_active=True, enrollment_date__lte=today,
    ))
    if not roster:
        raise ValidationError({"code": "ATTENDANCE_EMPTY_ROSTER", "detail": "لا يوجد طلاب فعالون في هذه الشعبة."})
    sent_ids = [item["enrollment"].pk for item in records]
    if len(sent_ids) != len(set(sent_ids)) or set(sent_ids) != {item.pk for item in roster}:
        raise ValidationError({"code": "ATTENDANCE_INVALID_ROSTER", "detail": "يجب أن يطابق الطلاب المرسلون قائمة طلاب الشعبة الفعالة كاملة."})
    cleaned = [(item["enrollment"], normalize_and_validate_record(item, final=True)) for item in records]
    try:
        with transaction.atomic():
            sheet = AttendanceSheet.objects.create(section=section, attendance_date=today, created_by=actor)
            AttendanceRecord.objects.bulk_create([
                AttendanceRecord(sheet=sheet, enrollment=enrollment, **{f: values[f] for f in ATTENDANCE_FIELDS})
                for enrollment, values in cleaned
            ])
    except IntegrityError as exc:
        if AttendanceSheet.objects.filter(section=section, attendance_date=today).exists():
            raise ValidationError({"code": "ATTENDANCE_SHEET_ALREADY_EXISTS", "detail": "تم أخذ حضور هذه الشعبة مسبقًا لهذا اليوم."}) from exc
        raise
    return sheet


@transaction.atomic
def update_attendance_record(*, record, data):
    record = AttendanceRecord.objects.select_for_update().get(pk=record.pk)
    values = normalize_and_validate_record(data, current=record)
    for field in ATTENDANCE_FIELDS:
        setattr(record, field, values[field])
    record.save(update_fields=[*ATTENDANCE_FIELDS, "updated_at"])
    return record


@transaction.atomic
def bulk_update_attendance(*, sheet, items):
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "لا يجوز تكرار السجل في الطلب."})
    records = {r.pk: r for r in AttendanceRecord.objects.select_for_update().filter(sheet=sheet, pk__in=ids)}
    if set(ids) != set(records):
        raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "أحد السجلات لا ينتمي إلى هذا الكشف."})
    changed = []
    now = timezone.now()
    for item in items:
        record = records[item["id"]]
        values = normalize_and_validate_record(item, current=record)
        for field in ATTENDANCE_FIELDS:
            setattr(record, field, values[field])
        record.updated_at = now
        changed.append(record)
    AttendanceRecord.objects.bulk_update(changed, [*ATTENDANCE_FIELDS, "updated_at"])
    return changed


@transaction.atomic
def apply_normal_departure(*, sheet, departure_time, departure_method):
    records = list(AttendanceRecord.objects.select_for_update().filter(
        sheet=sheet, status=AttendanceRecord.Status.PRESENT, departure_time__isnull=True,
    ))
    for record in records:
        values = normalize_and_validate_record({"departure_time": departure_time, "departure_method": departure_method}, current=record)
        record.departure_time = values["departure_time"]
        record.departure_method = values["departure_method"]
        record.updated_at = timezone.now()
    AttendanceRecord.objects.bulk_update(records, ["departure_time", "departure_method", "updated_at"])
    return records
