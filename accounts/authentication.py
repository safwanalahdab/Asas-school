from django.conf import settings
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import (
    JWTAuthentication,
)


def enforce_csrf(request):
    """
    يطبق فحص CSRF على الطلب الحالي.
    """

    csrf_check = CSRFCheck(
        lambda current_request: None,
    )

    csrf_check.process_request(request)

    failure_reason = csrf_check.process_view(
        request,
        None,
        (),
        {},
    )

    if failure_reason:
        raise PermissionDenied(
            {
                "code": "CSRF_FAILED",
                "detail": "فشل التحقق من رمز الحماية. يرجى تحديث الصفحة والمحاولة مجدداً.",
            }
        )


class CookieJWTAuthentication(JWTAuthentication):
    """
    يقرأ Access Token من HttpOnly Cookie.

    ويبقي دعم Authorization Header للاختبارات
    وSwagger، لكن النظام الأساسي يعتمد على Cookie.
    """

    def authenticate(self, request):
        header = self.get_header(request)
        using_cookie = False

        if header is not None:
            raw_token = self.get_raw_token(header)
        else:
            raw_token = request.COOKIES.get(
                settings.JWT_ACCESS_COOKIE_NAME,
            )
            using_cookie = True

        if raw_token is None:
            return None

        validated_token = self.get_validated_token(
            raw_token,
        )

        # نطبق CSRF فقط عندما جاءت المصادقة من Cookie.
        # Authorization Header لا يرسل تلقائياً من المتصفح.
        if (
            using_cookie
            and request.method not in SAFE_METHODS
        ):
            enforce_csrf(request)

        user = self.get_user(validated_token)

        if (
            validated_token.get("client") != "web"
            or validated_token.get("token_version") != user.token_version
        ):
            raise AuthenticationFailed(
                {"code": "TOKEN_VERSION_INVALID", "detail": "انتهت صلاحية الجلسة."}
            )

        return user, validated_token
