from rest_framework import status
from rest_framework.response import Response


DEFAULT_SUCCESS_MESSAGES = {
    "list": ("RECORDS_RETRIEVED", "تم جلب البيانات بنجاح."),
    "retrieve": ("RECORD_RETRIEVED", "تم جلب البيانات المطلوبة بنجاح."),
    "create": ("RECORD_CREATED", "تمت إضافة البيانات بنجاح."),
    "update": ("RECORD_UPDATED", "تم تحديث البيانات بنجاح."),
    "partial_update": ("RECORD_UPDATED", "تم تحديث البيانات بنجاح."),
    "destroy": ("RECORD_DELETED", "تم حذف البيانات بنجاح."),
}


def requester_role_meta(request):
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        requester_role = None
    elif getattr(user, "is_superuser", False):
        requester_role = {"code": "superuser", "label": "مدير النظام"}
    else:
        role = getattr(user, "role", None)
        requester_role = (
            {"code": role, "label": user.get_role_display()} if role else None
        )
    return {"requester_role": requester_role}


def success_response(*, code, message, data=None, status_code=status.HTTP_200_OK):
    body = {"success": True, "code": code.upper(), "message": message}
    if data is not None:
        body["data"] = data
    return Response(body, status=status_code)


class ArabicApiResponseMixin:
    """Turn every successful DRF response into the public API envelope."""

    response_messages = {}

    def get_response_message(self):
        action = getattr(self, "action", None)
        if action is None:
            action = self.request.method.lower()
        return self.response_messages.get(
            action,
            DEFAULT_SUCCESS_MESSAGES.get(
                action, ("REQUEST_SUCCEEDED", "تم تنفيذ الطلب بنجاح.")
            ),
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if (
            getattr(response, "exception", False)
            or not 200 <= response.status_code < 300
        ):
            return response
        if isinstance(response.data, dict) and "success" in response.data:
            response.data["meta"] = requester_role_meta(request)
            return response

        code, message = self.get_response_message()
        payload = response.data
        if response.status_code == status.HTTP_204_NO_CONTENT:
            response.status_code = status.HTTP_200_OK
            response.data = {
                "success": True,
                "code": str(code).upper(),
                "message": str(message),
                "meta": requester_role_meta(request),
            }
            return response
        if payload is None:
            return response
        if isinstance(payload, dict):
            payload = payload.copy()
            code = payload.pop("code", code)
            message = payload.pop("message", payload.pop("detail", message))
            if set(payload) == {"data"}:
                payload = payload["data"]

        response.data = {
            "success": True,
            "code": str(code).upper(),
            "message": str(message),
            "data": payload,
            "meta": requester_role_meta(request),
        }
        return response
