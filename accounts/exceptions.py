from rest_framework import status
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.views import exception_handler as drf_exception_handler


STATUS_CODES = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "AUTHENTICATION_FAILED",
    status.HTTP_403_FORBIDDEN: "PERMISSION_DENIED",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_406_NOT_ACCEPTABLE: "NOT_ACCEPTABLE",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "UNSUPPORTED_MEDIA_TYPE",
    status.HTTP_429_TOO_MANY_REQUESTS: "THROTTLED",
}

STATUS_DETAILS = {
    status.HTTP_400_BAD_REQUEST: "يرجى تصحيح البيانات المدخلة.",
    status.HTTP_401_UNAUTHORIZED: "تعذر التحقق من بيانات المصادقة.",
    status.HTTP_403_FORBIDDEN: "ليس لديك صلاحية لتنفيذ هذا الإجراء.",
    status.HTTP_404_NOT_FOUND: "العنصر المطلوب غير موجود.",
    status.HTTP_405_METHOD_NOT_ALLOWED: "طريقة الطلب غير مسموحة.",
    status.HTTP_406_NOT_ACCEPTABLE: "صيغة الاستجابة المطلوبة غير مدعومة.",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "نوع محتوى الطلب غير مدعوم.",
    status.HTTP_429_TOO_MANY_REQUESTS: "تم تجاوز عدد المحاولات المسموح بها. يرجى المحاولة لاحقاً.",
}


def _plain(value):
    if isinstance(value, ErrorDetail):
        return str(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    data = _plain(response.data)
    explicit_code = data.get("code") if isinstance(data, dict) else None
    explicit_detail = data.get("detail") if isinstance(data, dict) else None

    if isinstance(exc, ValidationError):
        fields = data if isinstance(data, dict) else {"non_field_errors": data}
        fields.pop("code", None)
        fields.pop("detail", None)
        response.data = {
            "code": explicit_code or "VALIDATION_ERROR",
            "detail": explicit_detail or STATUS_DETAILS[status.HTTP_400_BAD_REQUEST],
            **fields,
        }
        return response

    response.data = {
        "code": explicit_code or STATUS_CODES.get(response.status_code, "API_ERROR"),
        "detail": explicit_detail or STATUS_DETAILS.get(
            response.status_code, "تعذر إكمال الطلب."
        ),
    }
    return response
