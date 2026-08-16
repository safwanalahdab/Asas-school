from rest_framework.exceptions import ValidationError

from .models import AttendanceRecord


ATTENDANCE_FIELDS = (
    "status", "arrival_time", "arrival_method", "departure_time",
    "departure_method", "absence_type", "absence_reason",
    "absence_reason_source", "notes",
)


def normalize_and_validate_record(data, *, current=None, final=False):
    values = {field: getattr(current, field, None) for field in ATTENDANCE_FIELDS}
    values.update(data)
    for field in ("arrival_method", "departure_method", "absence_type", "absence_reason", "absence_reason_source", "notes"):
        if values[field] is None:
            values[field] = ""
    status = values.get("status") or AttendanceRecord.Status.UNMARKED

    if status == AttendanceRecord.Status.UNMARKED:
        if final:
            raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "يجب تحديد حالة كل طالب قبل حفظ الكشف."})
        for field in ATTENDANCE_FIELDS[1:-1]:
            values[field] = None if field.endswith("_time") else ""
    elif status == AttendanceRecord.Status.PRESENT:
        if any(values.get(field) for field in ("absence_type", "absence_reason", "absence_reason_source")):
            raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "لا يمكن إضافة بيانات غياب لطالب حاضر."})
    elif status == AttendanceRecord.Status.ABSENT:
        if not values.get("absence_type"):
            raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "نوع الغياب مطلوب للطالب الغائب."})
        if any(values.get(field) for field in ("arrival_time", "arrival_method", "departure_time", "departure_method")):
            raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "لا يمكن إضافة بيانات وصول أو مغادرة لطالب غائب."})
        if values["absence_type"] == AttendanceRecord.AbsenceType.EXCUSED and (
            not str(values.get("absence_reason") or "").strip() or not values.get("absence_reason_source")
        ):
            raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "سبب الغياب ومصدره مطلوبان للغياب بعذر."})

    if values.get("arrival_time") and values.get("departure_time") and values["departure_time"] < values["arrival_time"]:
        raise ValidationError({"code": "ATTENDANCE_RECORD_INVALID", "detail": "وقت المغادرة لا يمكن أن يسبق وقت الوصول."})
    return values
