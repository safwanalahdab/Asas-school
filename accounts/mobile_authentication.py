from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class MobileJWTAuthentication(JWTAuthentication):
    """Authenticate only header-borne access tokens issued to the mobile client."""

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        if (
            validated_token.get("client") != "mobile"
            or validated_token.get("token_version") != user.token_version
        ):
            raise AuthenticationFailed(
                {"code": "TOKEN_VERSION_INVALID", "detail": "انتهت صلاحية الجلسة."}
            )
        return user, validated_token


class MobileJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.mobile_authentication.MobileJWTAuthentication"
    name = "MobileBearerAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
