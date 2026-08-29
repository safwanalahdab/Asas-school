from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

from accounts.services import temporary_password_is_expired

User = get_user_model()
DUMMY_PASSWORD_HASH = make_password("mobile-login-dummy-password")
INVALID_CREDENTIALS = {
    "code": "INVALID_CREDENTIALS",
    "detail": "اسم المستخدم أو كلمة المرور غير صحيحة.",
}


class MobileGuardianSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id", "username", "first_name", "last_name", "email", "role",
            "must_change_password",
        )
        read_only_fields = fields


class MobileLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254, write_only=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        identifier = attrs["identifier"].strip()
        candidate = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).first()
        authenticated = None
        if candidate is None:
            check_password(attrs["password"], DUMMY_PASSWORD_HASH)
        else:
            authenticated = authenticate(
                request=self.context.get("request"),
                username=candidate.username,
                password=attrs["password"],
            )
        if not (
            authenticated
            and authenticated.is_active
            and authenticated.role == User.Role.GUARDIAN
        ):
            raise AuthenticationFailed(INVALID_CREDENTIALS)
        if temporary_password_is_expired(authenticated):
            raise AuthenticationFailed({
                "code": "TEMPORARY_PASSWORD_EXPIRED",
                "detail": "انتهت صلاحية كلمة المرور المؤقتة.",
            })

        refresh = RefreshToken.for_user(authenticated)
        refresh["client"] = "mobile"
        refresh["token_version"] = authenticated.token_version
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": authenticated,
        }


class MobileTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        try:
            token = self.token_class(attrs["refresh"])
        except TokenError as exc:
            raise AuthenticationFailed({
                "code": "INVALID_REFRESH_TOKEN",
                "detail": "رمز التحديث غير صالح أو منتهي الصلاحية.",
            }) from exc
        if token.get("client") != "mobile":
            raise AuthenticationFailed({
                "code": "INVALID_REFRESH_CLIENT",
                "detail": "رمز التحديث لا يخص تطبيق ولي الأمر.",
            })
        user_id = token.get(api_settings.USER_ID_CLAIM)
        try:
            user = User.objects.get(**{api_settings.USER_ID_FIELD: user_id})
        except (User.DoesNotExist, TypeError, ValueError) as exc:
            raise AuthenticationFailed({
                "code": "INVALID_REFRESH_USER", "detail": "جلسة المستخدم غير صالحة."
            }) from exc
        if not user.is_active or user.role != User.Role.GUARDIAN:
            raise AuthenticationFailed({
                "code": "MOBILE_GUARDIAN_ACCESS_DENIED",
                "detail": "هذا الحساب غير مخول لاستخدام تطبيق ولي الأمر.",
            })
        if token.get("token_version") != user.token_version:
            raise AuthenticationFailed({
                "code": "TOKEN_VERSION_INVALID", "detail": "انتهت صلاحية الجلسة."
            })
        if temporary_password_is_expired(user):
            raise AuthenticationFailed({
                "code": "TEMPORARY_PASSWORD_EXPIRED",
                "detail": "انتهت صلاحية كلمة المرور المؤقتة.",
            })
        data = super().validate(attrs)
        # SimpleJWT rotation preserves custom claims; set them explicitly as a
        # defense against future library behavior changes.
        if "refresh" in data:
            rotated = RefreshToken(data["refresh"])
            rotated["client"] = "mobile"
            rotated["token_version"] = user.token_version
            data["refresh"] = str(rotated)
            data["access"] = str(rotated.access_token)
        return data


class MobileLogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True)

    def validate_refresh(self, raw_token):
        try:
            token = UntypedToken(raw_token)
        except TokenError as exc:
            raise AuthenticationFailed({
                "code": "INVALID_REFRESH_TOKEN",
                "detail": "رمز التحديث غير صالح أو منتهي الصلاحية.",
            }) from exc
        if token.get("token_type") != "refresh" or token.get("client") != "mobile":
            raise AuthenticationFailed({
                "code": "INVALID_REFRESH_CLIENT",
                "detail": "رمز التحديث لا يخص تطبيق ولي الأمر.",
            })
        return raw_token

    def save(self, **kwargs):
        try:
            RefreshToken(self.validated_data["refresh"]).blacklist()
        except TokenError:
            # Signature, expiry, type, and client were already verified above;
            # this is the expected path for an already-blacklisted token.
            pass


class MobileTokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class MobileLoginDataSerializer(MobileTokenPairSerializer):
    user = MobileGuardianSerializer()


class MobileResponseMetaSerializer(serializers.Serializer):
    requester_role = serializers.JSONField(allow_null=True)


class MobileSuccessEnvelopeSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField()
    message = serializers.CharField()
    meta = MobileResponseMetaSerializer()


class MobileLoginResponseSerializer(MobileSuccessEnvelopeSerializer):
    code = serializers.CharField(default="MOBILE_LOGIN_SUCCESS")
    data = MobileLoginDataSerializer()


class MobileRefreshResponseSerializer(MobileSuccessEnvelopeSerializer):
    code = serializers.CharField(default="MOBILE_SESSION_REFRESHED")
    data = MobileTokenPairSerializer()


class MobileLogoutResponseSerializer(MobileSuccessEnvelopeSerializer):
    code = serializers.CharField(default="MOBILE_LOGOUT_SUCCESS")
    data = serializers.JSONField(default=dict)


class MobileMeResponseSerializer(MobileSuccessEnvelopeSerializer):
    code = serializers.CharField(default="MOBILE_CURRENT_USER_RETRIEVED")
    data = MobileGuardianSerializer()


class MobileChangePasswordResponseSerializer(MobileSuccessEnvelopeSerializer):
    code = serializers.CharField(default="MOBILE_PASSWORD_CHANGED")
    data = serializers.JSONField(default=dict)
