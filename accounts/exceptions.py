import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    ErrorDetail,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from config.api_responses import requester_role_meta


logger = logging.getLogger(__name__)

ERROR_TRANSLATIONS = {
    "required": "هذا الحقل مطلوب.",
    "invalid": "القيمة المدخلة غير صحيحة.",
    "does_not_exist": "المعرّف المحدد غير موجود.",
    "incorrect_type": "القيمة المدخلة من نوع غير صحيح.",
    "invalid_choice": "الاختيار المحدد غير صالح.",
    "date": "أدخل تاريخًا صالحًا.",
    "unique": "هذه القيمة مستخدمة مسبقًا.",
    "blank": "لا يمكن ترك هذا الحقل فارغًا.",
    "null": "لا يمكن أن تكون قيمة هذا الحقل فارغة.",
}


def _arabic_errors(value):
    if isinstance(value, ErrorDetail):
        message = str(value)
        if any("\u0600" <= character <= "\u06ff" for character in message):
            return message
        return ERROR_TRANSLATIONS.get(value.code, message)
    if isinstance(value, list):
        return [_arabic_errors(item) for item in value]
    if isinstance(value, dict):
        return {key: _arabic_errors(item) for key, item in value.items()}
    return value


def _explicit_metadata(data):
    if not isinstance(data, dict):
        return None, None, data
    data = data.copy()
    return data.pop("code", None), data.pop("message", data.pop("detail", None)), data


def api_exception_handler(exc, context):
    meta = requester_role_meta(context.get("request"))
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API exception", exc_info=exc)
        return Response(
            {
                "success": False,
                "code": "INTERNAL_SERVER_ERROR",
                "message": "حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى لاحقًا.",
                "meta": meta,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code, message, errors = _explicit_metadata(response.data)
    body = {"success": False}

    if isinstance(exc, ValidationError):
        body.update(
            code=(code or "VALIDATION_ERROR").upper(),
            message=message or "تعذّر حفظ البيانات. يرجى مراجعة الحقول الموضّحة.",
        )
        cleaned = _arabic_errors(errors)
        if cleaned not in ({}, [], None):
            body["errors"] = (
                cleaned if isinstance(cleaned, dict) else {"non_field_errors": cleaned}
            )
    elif isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        response.status_code = status.HTTP_401_UNAUTHORIZED
        body.update(
            code=(code or "AUTHENTICATION_REQUIRED").upper(),
            message=message or "انتهت صلاحية جلسة تسجيل الدخول. يرجى تسجيل الدخول مرة أخرى.",
        )
    elif isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        body.update(
            code=(code or "PERMISSION_DENIED").upper(),
            message=message or "ليس لديك صلاحية لتنفيذ هذا الإجراء.",
        )
    elif isinstance(exc, (NotFound, Http404)):
        body.update(code=(code or "NOT_FOUND").upper(), message=message or "لم يتم العثور على السجل المطلوب.")
    elif isinstance(exc, MethodNotAllowed):
        body.update(code=(code or "METHOD_NOT_ALLOWED").upper(), message=message or "هذا الإجراء غير مدعوم.")
    elif isinstance(exc, Throttled):
        body.update(code=(code or "TOO_MANY_REQUESTS").upper(), message=message or "تم تجاوز عدد المحاولات المسموح بها. يرجى المحاولة لاحقًا.")
    else:
        body.update(code=(code or "API_ERROR").upper(), message=message or "تعذّر إكمال الطلب.")

    body["meta"] = meta
    response.data = body
    return response
