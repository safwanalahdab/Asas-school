from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from academics.models import Section
from audit_logs.models import AuditLog
from audit_logs.services import get_actor_display, record_audit_event
from notifications.services import create_notification
from students.models import Enrollment, GuardianStudent, StudentAuditLog
from .domain import ATTENDANCE_FIELDS, normalize_and_validate_record
from .models import AttendanceRecord, AttendanceSheet


def _notify_final_absences(records):
    absent_records = [
        record for record in records
        if record.status == AttendanceRecord.Status.ABSENT
    ]
    guardian_links = {
        link.student_id: link
        for link in GuardianStudent.objects.filter(
            student_id__in=[record.enrollment.student_id for record in absent_records],
            student__is_active=True,
            guardian__is_active=True,
            guardian__role="guardian",
            is_active=True,
        ).select_related("guardian", "student")
    }
    for record in absent_records:
        guardian_link = guardian_links.get(record.enrollment.student_id)
        if guardian_link is None:
            continue
        create_notification(
            recipient=guardian_link.guardian,
            notification_type="attendance",
            title="تسجيل غياب",
            body="تم تسجيل غياب للطالب. يمكنك مراجعة تفاصيل الحضور داخل التطبيق.",
            student=guardian_link.student,
            resource_type="attendance",
            resource_id=record.id,
            event_key=f"attendance:{record.id}:absent",
        )


def get_effective_attendance_roster(*, section, attendance_date):
    current_timezone = timezone.get_current_timezone()
    day_start = timezone.make_aware(
        datetime.combine(attendance_date, time.min), current_timezone
    )
    next_day_start = timezone.make_aware(
        datetime.combine(attendance_date + timedelta(days=1), time.min),
        current_timezone,
    )
    day_transfers = StudentAuditLog.objects.filter(
        event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
        created_at__gte=day_start,
        created_at__lt=next_day_start,
    )
    transfer_candidate_ids = day_transfers.filter(
        Q(old_section=section) | Q(new_section=section)
    ).values_list("enrollment_id", flat=True)
    candidates = list(
        Enrollment.objects.select_related("student").filter(
            Q(section=section) | Q(pk__in=transfer_candidate_ids),
            student__is_active=True,
            enrollment_date__lte=attendance_date,
        ).distinct()
    )
    earliest_old_sections = {}
    for enrollment_id, old_section_id in day_transfers.filter(
        enrollment_id__in=[enrollment.pk for enrollment in candidates]
    ).order_by("created_at", "pk").values_list("enrollment_id", "old_section_id"):
        earliest_old_sections.setdefault(enrollment_id, old_section_id)
    return [
        enrollment for enrollment in candidates
        if earliest_old_sections.get(enrollment.pk, enrollment.section_id) == section.pk
    ]


@transaction.atomic
def create_attendance_sheet(*, section, actor, records):
    today = timezone.localdate()
    if today.weekday() in {4, 5}:
        raise ValidationError({"code": "ATTENDANCE_NOT_ALLOWED_ON_WEEKEND", "detail": "لا يمكن تسجيل الحضور يومي الجمعة والسبت."})
    section = Section.objects.select_for_update().get(pk=section.pk)
    if AttendanceSheet.objects.filter(section=section, attendance_date=today).exists():
        raise ValidationError({"code": "ATTENDANCE_SHEET_ALREADY_EXISTS", "detail": "تم أخذ حضور هذه الشعبة مسبقًا لهذا اليوم."})

    roster = get_effective_attendance_roster(
        section=section,
        attendance_date=today,
    )
    if not roster:
        raise ValidationError({"code": "ATTENDANCE_EMPTY_ROSTER", "detail": "لا يوجد طلاب فعالون في هذه الشعبة."})
    sent_ids = [item["enrollment"].pk for item in records]
    if len(sent_ids) != len(set(sent_ids)) or set(sent_ids) != {item.pk for item in roster}:
        raise ValidationError({"code": "ATTENDANCE_INVALID_ROSTER", "detail": "يجب أن يطابق الطلاب المرسلون قائمة طلاب الشعبة الفعالة كاملة."})
    cleaned = [
        (item["enrollment"], normalize_and_validate_record(item, final=True, morning=True))
        for item in records
    ]
    try:
        with transaction.atomic():
            sheet = AttendanceSheet.objects.create(section=section, attendance_date=today, created_by=actor)
            attendance_records = AttendanceRecord.objects.bulk_create([
                AttendanceRecord(sheet=sheet, enrollment=enrollment, **{f: values[f] for f in ATTENDANCE_FIELDS})
                for enrollment, values in cleaned
            ])
    except IntegrityError as exc:
        if AttendanceSheet.objects.filter(section=section, attendance_date=today).exists():
            raise ValidationError({"code": "ATTENDANCE_SHEET_ALREADY_EXISTS", "detail": "تم أخذ حضور هذه الشعبة مسبقًا لهذا اليوم."}) from exc
        raise
    record_audit_event(
        actor=actor,
        module=AuditLog.Module.ATTENDANCE,
        action=AuditLog.Action.CREATE,
        message=f"أنشأ {get_actor_display(actor)} كشف حضور الشعبة {section}.",
        target=sheet,
        metadata={
            "section": str(section),
            "attendance_date": today,
            "students_count": len(cleaned),
        },
    )
    _notify_final_absences(attendance_records)
    return sheet


@transaction.atomic
def update_attendance_record(*, record, data):
    record = AttendanceRecord.objects.select_for_update().get(pk=record.pk)
    was_absent = record.status == AttendanceRecord.Status.ABSENT
    values = normalize_and_validate_record(data, current=record)
    for field in ATTENDANCE_FIELDS:
        setattr(record, field, values[field])
    record.save(update_fields=[*ATTENDANCE_FIELDS, "updated_at"])
    if not was_absent and record.status == AttendanceRecord.Status.ABSENT:
        _notify_final_absences([record])
    return record


@transaction.atomic
def bulk_update_attendance(*, sheet, items, actor=None):
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "لا يجوز تكرار السجل في الطلب."})
    records = {r.pk: r for r in AttendanceRecord.objects.select_for_update().filter(sheet=sheet, pk__in=ids)}
    if set(ids) != set(records):
        raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "أحد السجلات لا ينتمي إلى هذا الكشف."})
    changed = []
    newly_absent = []
    now = timezone.now()
    for item in items:
        record = records[item["id"]]
        was_absent = record.status == AttendanceRecord.Status.ABSENT
        values = normalize_and_validate_record(item, current=record)
        if not any(
            getattr(record, field) != values[field]
            for field in ATTENDANCE_FIELDS
        ):
            continue
        for field in ATTENDANCE_FIELDS:
            setattr(record, field, values[field])
        record.updated_at = now
        changed.append(record)
        if not was_absent and record.status == AttendanceRecord.Status.ABSENT:
            newly_absent.append(record)
    changed_count = len(changed)
    if changed:
        AttendanceRecord.objects.bulk_update(changed, [*ATTENDANCE_FIELDS, "updated_at"])
    if changed_count:
        record_audit_event(
            actor=actor,
            module=AuditLog.Module.ATTENDANCE,
            action=AuditLog.Action.UPDATE,
            message=f"حدّث {get_actor_display(actor)} سجلات حضور الشعبة {sheet.section}.",
            target=sheet,
            metadata={
                "section": str(sheet.section),
                "attendance_date": sheet.attendance_date,
                "submitted_count": len(items),
                "changed_count": changed_count,
            },
        )
    _notify_final_absences(newly_absent)
    return changed


@transaction.atomic
def apply_normal_departure(*, sheet, departure_time, departure_method, actor=None):
    records = list(AttendanceRecord.objects.select_for_update().filter(
        sheet=sheet, status=AttendanceRecord.Status.PRESENT, departure_time__isnull=True,
    ))
    for record in records:
        values = normalize_and_validate_record({"departure_time": departure_time, "departure_method": departure_method}, current=record)
        record.departure_time = values["departure_time"]
        record.departure_method = values["departure_method"]
        record.updated_at = timezone.now()
    AttendanceRecord.objects.bulk_update(records, ["departure_time", "departure_method", "updated_at"])
    if records:
        record_audit_event(
            actor=actor,
            module=AuditLog.Module.ATTENDANCE,
            action=AuditLog.Action.UPDATE,
            message=f"سجّل {get_actor_display(actor)} المغادرة الطبيعية للشعبة {sheet.section}.",
            target=sheet,
            metadata={
                "section": str(sheet.section),
                "attendance_date": sheet.attendance_date,
                "affected_count": len(records),
                "departure_time": departure_time,
                "departure_method": departure_method,
            },
        )
    return records
