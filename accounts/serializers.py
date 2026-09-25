from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q

from rest_framework import serializers
from rest_framework.exceptions import (
    AuthenticationFailed,
    PermissionDenied,
)

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import (
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.policies import (
    can_access_web_dashboard,
    can_change_account_role,
    can_create_role,
    can_update_account,
)
from accounts.services import (
    assign_temporary_password,
    change_user_role,
    increment_token_version,
    temporary_password_is_expired,
)
from accounts.permission_catalog import effective_business_permission_codes
from academics.models import GradeLevel, SupervisorScope
from academics.supervisor_scope_services import set_supervisor_scope

User = get_user_model()


class SupervisorScopeInputSerializer(serializers.Serializer):
    scope_type = serializers.ChoiceField(choices=SupervisorScope.ScopeType.choices)
    stages = serializers.ListField(
        child=serializers.ChoiceField(choices=GradeLevel.Stage.choices),
        allow_empty=True,
    )

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "هذا الحقل غير مسموح به." for name in unknown}
            )
        stages = attrs["stages"]
        if len(stages) != len(set(stages)):
            raise serializers.ValidationError(
                {"stages": "لا يجوز تكرار المرحلة ضمن النطاق."}
            )
        if attrs["scope_type"] == SupervisorScope.ScopeType.ALL and stages:
            raise serializers.ValidationError(
                {"stages": "يجب أن تكون المراحل فارغة للنطاق الشامل."}
            )
        if (
            attrs["scope_type"] == SupervisorScope.ScopeType.SELECTED_STAGES
            and not stages
        ):
            raise serializers.ValidationError(
                {"stages": "يجب اختيار مرحلة واحدة على الأقل."}
            )
        return attrs


class SupervisorScopeField(serializers.Field):
    def get_attribute(self, instance):
        return instance

    def to_internal_value(self, data):
        serializer = SupervisorScopeInputSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def to_representation(self, user):
        if user.role != User.Role.SUPERVISOR:
            return None
        try:
            scope = user.supervisor_scope
        except SupervisorScope.DoesNotExist:
            return None
        selected = set(scope.stages.values_list("stage", flat=True))
        ordered = [stage for stage in GradeLevel.Stage.values if stage in selected]
        return {
            "scope_type": scope.scope_type,
            "scope_type_display": scope.get_scope_type_display(),
            "stages": ordered,
            "stages_display": [GradeLevel.Stage(stage).label for stage in ordered],
        }

REQUIRED = "هذا الحقل مطلوب."
BLANK = "لا يجوز أن يكون هذا الحقل فارغاً."


class UserSummarySerializer(serializers.ModelSerializer):
    """
    البيانات الأساسية التي نرجعها عن المستخدم
    بعد تسجيل الدخول أو عند طلب /me/.
    """

    role_display = serializers.CharField(
        source="get_role_display",
        read_only=True,
    )
    supervisor_scope = SupervisorScopeField(source="*", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "role_display",
            "supervisor_scope",
            "must_change_password",
        ]
        read_only_fields = fields


class WebLoginSerializer(serializers.Serializer):
    """
    يستقبل اسم المستخدم أو البريد الإلكتروني وكلمة المرور.

    ينشئ Access Token وRefresh Token داخلياً،
    لكنه لا يرجعهما ضمن استجابة JSON.
    """

    identifier = serializers.CharField(
        write_only=True,
        max_length=254,
        error_messages={"required": REQUIRED, "blank": BLANK, "max_length": "تأكد من ألا يتجاوز هذا الحقل 254 محرفاً."},
    )

    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={
            "input_type": "password",
        },
        error_messages={"required": REQUIRED, "blank": BLANK},
    )

    def validate(self, attrs):
        identifier = attrs["identifier"].strip()
        password = attrs["password"]
        request = self.context.get("request")

        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ).first()

        if user is None:
            raise AuthenticationFailed(
                {"code": "INVALID_CREDENTIALS", "detail": "اسم المستخدم أو كلمة المرور غير صحيحة."}
            )

        authenticated_user = authenticate(
            request=request,
            username=user.username,
            password=password,
        )

        if authenticated_user is None:
            raise AuthenticationFailed(
                {"code": "INVALID_CREDENTIALS", "detail": "اسم المستخدم أو كلمة المرور غير صحيحة."}
            )

        if not can_access_web_dashboard(
            authenticated_user,
        ):
            raise PermissionDenied(
                {"code": "WEB_DASHBOARD_ACCESS_DENIED", "detail": "هذا الحساب غير مخول لاستخدام لوحة الإدارة."}
            )

        if temporary_password_is_expired(authenticated_user):
            raise AuthenticationFailed(
                {
                    "code": "TEMPORARY_PASSWORD_EXPIRED",
                    "detail": "انتهت صلاحية كلمة المرور المؤقتة.",
                }
            )

        refresh_token = RefreshToken.for_user(
            authenticated_user,
        )

        # نميز أن التوكن صدر من تسجيل دخول لوحة الويب.
        refresh_token["client"] = "web"

        # نخزن إصدار جلسات المستخدم الحالي داخل التوكن.
        # عند تغيير كلمة المرور سيرتفع الإصدار في قاعدة
        # البيانات، وبالتالي ستصبح التوكنات القديمة مرفوضة.
        refresh_token["token_version"] = authenticated_user.token_version

        # نخزن التوكنات مؤقتاً داخل كائن الـSerializer.
        # الـView ستقرأها وتضعها في HttpOnly Cookies.
        self.access_token = str(
            refresh_token.access_token,
        )
        self.refresh_token = str(
            refresh_token,
        )

        # نرجع المستخدم داخلياً للـView فقط.
        # لن يتحول كائن User نفسه مباشرة إلى JSON.
        return {
            "user": authenticated_user,
        }


class WebLoginResponseSerializer(serializers.Serializer):
    """
    شكل استجابة Login الظاهر في Swagger.

    لا نعرض Access أوRefresh Token لأنهما
    يوضعان داخل HttpOnly Cookies.
    """

    class LoginDataSerializer(serializers.Serializer):
        user = UserSummarySerializer()

    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="LOGIN_SUCCESS")
    message = serializers.CharField(default="تم تسجيل الدخول بنجاح.")
    data = LoginDataSerializer()


class WebTokenRefreshSerializer(TokenRefreshSerializer):
    """
    يتحقق من Refresh Token ويصدر توكنات جديدة،
    لكن فقط إذا:

    - كان التوكن صادراً من Web Login.
    - كان المستخدم ما زال موجوداً.
    - كان token_version مطابقاً للإصدار الحالي
      الموجود في قاعدة البيانات.
    """

    def validate(self, attrs):
        try:
            refresh_token = self.token_class(
                attrs["refresh"],
            )
        except TokenError as exc:
            raise AuthenticationFailed(
                {"code": "INVALID_REFRESH_TOKEN", "detail": "رمز التحديث غير صالح أو منتهي الصلاحية."}
            ) from exc

        # نمنع استخدام Refresh Token صادر من تطبيق
        # مختلف، مثل تطبيق ولي الأمر مستقبلاً.
        if refresh_token.get("client") != "web":
            raise AuthenticationFailed(
                {"code": "INVALID_REFRESH_CLIENT", "detail": "رمز التحديث لا يخص لوحة الإدارة."}
            )

        # نقرأ معرف المستخدم من التوكن.
        # اسم الحقل يؤخذ من إعدادات SimpleJWT
        # بدلاً من كتابة user_id بصورة ثابتة.
        user_id = refresh_token.get(
            api_settings.USER_ID_CLAIM,
        )

        if user_id is None:
            raise AuthenticationFailed(
                {"code": "INVALID_REFRESH_USER", "detail": "رمز التحديث لا يحتوي بيانات مستخدم صالحة."}
            )

        try:
            user = User.objects.only(
                "token_version",
                "must_change_password",
                "temporary_password_expires_at",
            ).get(
                **{
                    api_settings.USER_ID_FIELD: user_id,
                }
            )
        except User.DoesNotExist as exc:
            raise AuthenticationFailed(
                {"code": "SESSION_USER_NOT_FOUND", "detail": "الحساب المرتبط بالجلسة غير موجود."}
            ) from exc

        # نقرأ الإصدار الذي كان موجوداً عند إنشاء التوكن.
        token_version = refresh_token.get(
            "token_version",
        )

        # نقارنه بالإصدار الحالي في قاعدة البيانات.
        # عدم وجود الحقل أيضاً يؤدي إلى الرفض، وبالتالي
        # التوكنات الصادرة قبل هذا التعديل لن تعمل.
        if token_version != user.token_version:
            raise AuthenticationFailed(
                {
                    "code": "TOKEN_VERSION_INVALID",
                    "detail": "انتهت صلاحية الجلسة. يرجى تسجيل الدخول من جديد.",
                }
            )

        if temporary_password_is_expired(user):
            raise AuthenticationFailed(
                {
                    "code": "TEMPORARY_PASSWORD_EXPIRED",
                    "detail": "انتهت صلاحية كلمة المرور المؤقتة.",
                }
            )

        # بعد اجتياز فحوصاتنا الأمنية، نشغّل منطق
        # SimpleJWT الأصلي لإنشاء Access Token جديد،
        # وتدوير Refresh Token وإلغاء القديم.
        return super().validate(attrs)


class MessageResponseSerializer(serializers.Serializer):
    """
    شكل الاستجابات التي ترجع رسالة فقط،
    مثل Refresh وLogout.
    """

    success = serializers.BooleanField(default=True)
    code = serializers.CharField()
    message = serializers.CharField()
    data = serializers.JSONField(required=False, allow_null=True)


class CsrfTokenResponseSerializer(serializers.Serializer):
    """
    شكل استجابة Endpoint الخاص بالحصول على CSRF Token.
    """

    class CsrfDataSerializer(serializers.Serializer):
        csrf_token = serializers.CharField()

    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="CSRF_TOKEN_RETRIEVED")
    message = serializers.CharField()
    data = CsrfDataSerializer()


class WebLogoutSerializer(serializers.Serializer):
    """
    يقرأ Refresh Token من HttpOnly Cookie
    ويضعه في Blacklist عند تسجيل الخروج.

    لا يستقبل Refresh Token من Request Body.
    """

    def validate(self, attrs):
        request = self.context["request"]

        raw_refresh_token = request.COOKIES.get(
            settings.JWT_REFRESH_COOKIE_NAME,
        )

        self.refresh_token = None

        # في حال لم يوجد Refresh Cookie،
        # نبقي Logout عملية آمنة وقابلة للتكرار.
        if raw_refresh_token is None:
            return attrs

        try:
            refresh_token = RefreshToken(
                raw_refresh_token,
            )
        except TokenError:
            # إذا كان منتهياً أو ملغياً سابقاً،
            # لا داعي لإرجاع خطأ أثناء Logout.
            return attrs

        if refresh_token.get("client") != "web":
            return attrs

        self.refresh_token = refresh_token

        return attrs

    def save(self, **kwargs):
        if self.refresh_token is not None:
            self.refresh_token.blacklist()


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False, error_messages={"required": REQUIRED, "blank": BLANK})
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, error_messages={"required": REQUIRED, "blank": BLANK})
    new_password_confirm = serializers.CharField(write_only=True, trim_whitespace=False, error_messages={"required": REQUIRED, "blank": BLANK})

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError(
                {"current_password": "كلمة المرور الحالية غير صحيحة."}
            )
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "كلمتا المرور غير متطابقتين."}
            )
        if user.check_password(attrs["new_password"]):
            raise serializers.ValidationError(
                {"new_password": "يجب أن تختلف كلمة المرور الجديدة عن الحالية."}
            )
        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"new_password": list(exc.messages)}
            ) from exc
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        with transaction.atomic():
            user.set_password(self.validated_data["new_password"])
            user.must_change_password = False
            user.temporary_password_expires_at = None
            user.save(
                update_fields=[
                    "password",
                    "must_change_password",
                    "temporary_password_expires_at",
                ]
            )
            increment_token_version(user)
        return user


class OptionalNationalIdSerializerMixin:
    def to_internal_value(self, data):
        if (
            "national_id" in data
            and isinstance(data.get("national_id"), str)
            and not data.get("national_id").strip()
        ):
            data = data.copy()
            data["national_id"] = None
        return super().to_internal_value(data)


class UserCreateSerializer(OptionalNationalIdSerializerMixin, serializers.ModelSerializer):
    temporary_password = serializers.CharField(read_only=True)
    supervisor_scope = SupervisorScopeField(required=False)
    forbidden_fields = {
        "password",
        "is_superuser",
        "is_staff",
        "token_version",
        "must_change_password",
        "temporary_password_expires_at",
    }

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "national_id",
            "phone_number",
            "email",
            "first_name",
            "last_name",
            "role",
            "supervisor_scope",
            "temporary_password",
        ]
        read_only_fields = ["id", "temporary_password"]
        extra_kwargs = {
            "username": {"error_messages": {"required": REQUIRED, "blank": BLANK, "unique": "اسم المستخدم مستخدم مسبقاً."}},
            "email": {"error_messages": {"invalid": "أدخل بريداً إلكترونياً صحيحاً."}},
            "first_name": {"error_messages": {"blank": BLANK}},
            "last_name": {"error_messages": {"blank": BLANK}},
            "role": {"error_messages": {"required": REQUIRED, "blank": BLANK, "invalid_choice": "الدور المحدد غير صالح."}},
        }

    def validate(self, attrs):
        supplied = self.forbidden_fields.intersection(self.initial_data)
        if supplied:
            raise serializers.ValidationError(
                {name: "هذا الحقل غير مسموح به." for name in supplied}
            )
        if not can_create_role(self.context["request"].user, attrs.get("role")):
            raise serializers.ValidationError({"role": "لا يمكنك إنشاء حساب بهذا الدور."})
        actor = self.context["request"].user
        role = attrs.get("role")
        scope_supplied = "supervisor_scope" in attrs
        if role == User.Role.SUPERVISOR:
            if not (actor.is_superuser or actor.role == User.Role.SCHOOL_ADMIN):
                raise serializers.ValidationError(
                    {"role": "فقط إدارة المدرسة تستطيع إنشاء حساب موجّه."}
                )
            if not scope_supplied:
                raise serializers.ValidationError(
                    {"supervisor_scope": "نطاق الموجّه مطلوب."}
                )
        elif scope_supplied:
            raise serializers.ValidationError(
                {"supervisor_scope": "هذا الحقل مسموح فقط لدور الموجّه."}
            )
        return attrs

    def create(self, validated_data):
        supervisor_scope = validated_data.pop("supervisor_scope", None)
        with transaction.atomic():
            user = User(**validated_data)
            password = assign_temporary_password(user)
            user.save()
            if supervisor_scope is not None:
                set_supervisor_scope(
                    supervisor=user,
                    scope_type=supervisor_scope["scope_type"],
                    stages=supervisor_scope["stages"],
                    actor=self.context["request"].user,
                )
        user.temporary_password = password
        return user


class ResetPasswordResponseSerializer(serializers.Serializer):
    class ResetPasswordDataSerializer(serializers.Serializer):
        temporary_password = serializers.CharField()

    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="PASSWORD_RESET")
    message = serializers.CharField()
    data = ResetPasswordDataSerializer()


class UserListSerializer(serializers.ModelSerializer):
    """
    يحدد البيانات التي تظهر في قائمة إدارة المستخدمين.

    هذا الـSerializer للعرض فقط، ولا يُستخدم
    لإنشاء المستخدم أو تعديل بياناته.
    """

    role_display = serializers.CharField(
        source="get_role_display",
        read_only=True,
    )

    full_name = serializers.SerializerMethodField()
    supervisor_scope = SupervisorScopeField(source="*", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "national_id",
            "phone_number",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "role_display",
            "supervisor_scope",
            "is_active",
            "must_change_password",
            "date_joined",
        ]

        read_only_fields = fields

    def get_full_name(self, user):
        """
        يجمع الاسم الأول واسم العائلة.

        إذا لم يكن المستخدم قد أدخل اسمه،
        نرجع اسم المستخدم بدلاً من نص فارغ.
        """

        full_name = user.get_full_name().strip()

        return full_name or user.username


class UserDetailSerializer(UserListSerializer):
    class Meta(UserListSerializer.Meta):
        fields = [*UserListSerializer.Meta.fields, "last_login"]
        read_only_fields = fields


class WebMeSerializer(UserSummarySerializer):
    permissions = serializers.SerializerMethodField()

    class Meta(UserSummarySerializer.Meta):
        fields = [*UserSummarySerializer.Meta.fields, "permissions"]
        read_only_fields = fields

    def get_permissions(self, user):
        return effective_business_permission_codes(user)


class WebMeUpdateSerializer(serializers.ModelSerializer):
    forbidden_fields = {
        "id",
        "username",
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
        "must_change_password",
        "temporary_password_expires_at",
        "token_version",
        "password",
    }

    email = serializers.EmailField(
        allow_blank=True,
        allow_null=True,
        required=False,
        error_messages={"invalid": "أدخل بريداً إلكترونياً صحيحاً."},
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        extra_kwargs = {
            "first_name": {"required": False},
            "last_name": {"required": False},
        }

    def validate(self, attrs):
        supplied = self.forbidden_fields.intersection(self.initial_data)
        if supplied:
            raise serializers.ValidationError(
                {name: "هذا الحقل غير مسموح به." for name in supplied}
            )
        return attrs

    def validate_email(self, value):
        if not value:
            return value
        duplicate_exists = User.objects.filter(email__iexact=value).exclude(
            pk=self.instance.pk
        ).exists()
        if duplicate_exists:
            raise serializers.ValidationError("البريد الإلكتروني مستخدم مسبقاً.")
        return value


class UserUpdateSerializer(OptionalNationalIdSerializerMixin, serializers.ModelSerializer):
    supervisor_scope = SupervisorScopeField(required=False)
    forbidden_fields = {
        "password",
        "is_active",
        "is_superuser",
        "is_staff",
        "must_change_password",
        "temporary_password_expires_at",
        "token_version",
    }

    class Meta:
        model = User
        fields = [
            "username",
            "national_id",
            "phone_number",
            "email",
            "first_name",
            "last_name",
            "role",
            "supervisor_scope",
        ]
        extra_kwargs = UserCreateSerializer.Meta.extra_kwargs

    def validate(self, attrs):
        supplied = self.forbidden_fields.intersection(self.initial_data)
        if supplied:
            raise serializers.ValidationError(
                {name: "هذا الحقل غير مسموح به." for name in supplied}
            )
        actor = self.context["request"].user
        if not can_update_account(actor, self.instance):
            raise PermissionDenied(
                {
                    "code": "ACCOUNT_UPDATE_FORBIDDEN",
                    "detail": "ليس لديك صلاحية لتعديل هذا الحساب أو تعيين الدور المطلوب.",
                }
            )
        role_supplied = "role" in self.initial_data
        scope_supplied = "supervisor_scope" in self.initial_data
        if (role_supplied or scope_supplied) and not can_change_account_role(
            actor, self.instance
        ):
            raise PermissionDenied(
                {
                    "code": "ACCOUNT_ROLE_OR_SCOPE_UPDATE_FORBIDDEN",
                    "detail": "فقط إدارة المدرسة تستطيع تعديل الدور أو نطاق الموجّه.",
                }
            )

        new_role = attrs.get("role", self.instance.role)
        role_changes = role_supplied and new_role != self.instance.role
        if role_changes and new_role == User.Role.SUPERVISOR and not scope_supplied:
            raise serializers.ValidationError(
                {"supervisor_scope": "نطاق الموجّه مطلوب عند تعيين هذا الدور."}
            )
        if scope_supplied and new_role != User.Role.SUPERVISOR:
            raise serializers.ValidationError(
                {"supervisor_scope": "هذا الحقل مسموح فقط لدور الموجّه."}
            )
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        supervisor_scope = validated_data.pop("supervisor_scope", None)
        new_role = validated_data.pop("role", instance.role)
        actor = self.context["request"].user
        instance = User.objects.select_for_update().get(pk=instance.pk)
        if not can_update_account(actor, instance):
            raise PermissionDenied(
                {
                    "code": "ACCOUNT_UPDATE_FORBIDDEN",
                    "detail": "ليس لديك صلاحية لتعديل هذا الحساب.",
                }
            )

        if new_role != instance.role:
            instance, _ = change_user_role(
                target=instance,
                new_role=new_role,
                actor=actor,
                supervisor_scope=supervisor_scope,
            )
        elif supervisor_scope is not None:
            set_supervisor_scope(
                supervisor=instance,
                scope_type=supervisor_scope["scope_type"],
                stages=supervisor_scope["stages"],
                actor=actor,
            )
            instance.refresh_from_db()

        return super().update(instance, validated_data)


class SetUserActiveSerializer(serializers.Serializer):
    is_active = serializers.BooleanField(
        error_messages={
            "required": REQUIRED,
            "invalid": "يجب أن تكون قيمة حالة الحساب صحيحة أو خاطئة.",
        }
    )

    
