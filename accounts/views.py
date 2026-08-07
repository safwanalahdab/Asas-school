from django.conf import settings
from django.contrib.auth import get_user_model
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    AuthenticationFailed,
    PermissionDenied,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import (
    CookieJWTAuthentication,
    enforce_csrf,
)
from accounts.cookies import (
    delete_auth_cookies,
    set_auth_cookies,
)
from accounts.permissions import CanViewAccounts, IsWebDashboardUser
from accounts.policies import (
    can_reset_account_password,
    can_set_account_active,
    get_visible_accounts_queryset,
)
from accounts.serializers import (
    ChangePasswordSerializer,
    CsrfTokenResponseSerializer,
    MessageResponseSerializer,
    ResetPasswordResponseSerializer,
    SetUserActiveSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserListSerializer,
    WebMeUpdateSerializer,
    UserSummarySerializer,
    UserUpdateSerializer,
    WebLoginResponseSerializer,
    WebLoginSerializer,
    WebLogoutSerializer,
    WebTokenRefreshSerializer,
)
from accounts.services import reset_account_password, set_account_active
from accounts.throttles import WebLoginRateThrottle


User = get_user_model()
@method_decorator(
    ensure_csrf_cookie,
    name="dispatch",
)
class WebCsrfView(APIView):
    """
    يرجع CSRF Token للواجهة ويضمن إنشاء CSRF Cookie.

    نستخدم هذا الـEndpoint قبل Login أو أي طلب
    POST / PUT / PATCH / DELETE يعتمد على Cookies.
    """

    # هذا المسار يجب أن يعمل قبل تسجيل الدخول.
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        responses={
            status.HTTP_200_OK: CsrfTokenResponseSerializer,
        },
    )
    def get(self, request):
        return Response(
            {
                "code": "CSRF_TOKEN_RETRIEVED",
                "detail": "تم الحصول على رمز الحماية بنجاح.",
                "csrf_token": get_token(request),
            },
            status=status.HTTP_200_OK,
        )


class WebLoginView(APIView):
    """
    يسجل دخول مستخدم لوحة الويب.

    ينشئ Access وRefresh Token ثم يضعهما داخل
    HttpOnly Cookies ولا يعيدهما ضمن JSON.
    """

    # المستخدم لا يمتلك Access Token قبل Login.
    authentication_classes = []
    permission_classes = []

    # نحد عدد محاولات تسجيل الدخول حسب IP.
    throttle_classes = [
        WebLoginRateThrottle,
    ]

    @extend_schema(
        request=WebLoginSerializer,
        responses={
            status.HTTP_200_OK: WebLoginResponseSerializer,
        },
    )
    def post(self, request):
        # نتحقق من CSRF لأن Login سينشئ
        # Cookies تستخدم لاحقاً في المصادقة.
        enforce_csrf(request)

        serializer = WebLoginSerializer(
            data=request.data,
            context={
                "request": request,
            },
        )

        serializer.is_valid(
            raise_exception=True,
        )

        user = serializer.validated_data["user"]

        # الـFrontend يستلم بيانات المستخدم فقط.
        response = Response(
            {
                "code": "LOGIN_SUCCESS",
                "detail": "تم تسجيل الدخول بنجاح.",
                "user": UserSummarySerializer(
                    user,
                ).data,
            },
            status=status.HTTP_200_OK,
        )

        # نخزن Access وRefresh داخل HttpOnly Cookies.
        set_auth_cookies(
            response=response,
            access_token=serializer.access_token,
            refresh_token=serializer.refresh_token,
        )

        return response


class WebTokenRefreshView(APIView):
    """
    يجدد جلسة لوحة الويب.

    يقرأ Refresh Token من HttpOnly Cookie،
    ثم يصدر Access وRefresh جديدين ويحدث Cookies.
    """

    # لا نشترط Access Token صالحاً؛
    # لأن Refresh يُستخدم عادة بعد انتهاء Access.
    authentication_classes = []
    permission_classes = []
    allow_password_change_required = True

    @extend_schema(
        request=None,
        responses={
            status.HTTP_200_OK: MessageResponseSerializer,
        },
    )
    def post(self, request):
        # Refresh طلب POST ويعتمد على Cookie،
        # لذلك يجب حمايته بواسطة CSRF.
        enforce_csrf(request)

        raw_refresh_token = request.COOKIES.get(
            settings.JWT_REFRESH_COOKIE_NAME,
        )

        if raw_refresh_token is None:
            raise AuthenticationFailed(
                {"code": "REFRESH_COOKIE_MISSING", "detail": "جلسة التحديث غير موجودة."}
            )

        # نمرر التوكن القادم من Cookie إلى Serializer
        # بدلاً من طلبه من الـFrontend داخل Body.
        serializer = WebTokenRefreshSerializer(
            data={
                "refresh": raw_refresh_token,
            },
        )

        serializer.is_valid(
            raise_exception=True,
        )

        new_access_token = serializer.validated_data["access"]

        # بسبب ROTATE_REFRESH_TOKENS=True
        # يرجع SimpleJWT Refresh Token جديداً.
        new_refresh_token = serializer.validated_data.get(
            "refresh",
            raw_refresh_token,
        )

        # لا نرجع التوكنات في JSON.
        response = Response(
            {
                "code": "SESSION_REFRESHED",
                "detail": "تم تجديد الجلسة بنجاح.",
            },
            status=status.HTTP_200_OK,
        )

        # نستبدل Cookies القديمة بالجديدة.
        set_auth_cookies(
            response=response,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
        )

        return response


class WebLogoutView(APIView):
    """
    يسجل خروج مستخدم لوحة الويب.

    يضع Refresh Token في Blacklist
    ثم يحذف Access وRefresh Cookies.
    """

    # نسمح بتنفيذ Logout حتى لو انتهى Access Token.
    authentication_classes = []
    permission_classes = []
    allow_password_change_required = True

    @extend_schema(
        request=None,
        responses={
            status.HTTP_200_OK: MessageResponseSerializer,
        },
    )
    def post(self, request):
        # Logout طلب POST ويعتمد على Cookie،
        # لذلك يجب التحقق من CSRF.
        enforce_csrf(request)

        serializer = WebLogoutSerializer(
            data={},
            context={
                "request": request,
            },
        )

        serializer.is_valid(
            raise_exception=True,
        )

        # يضع Refresh Token في Blacklist
        # إذا كان موجوداً وصالحاً.
        serializer.save()

        response = Response(
            {
                "code": "LOGOUT_SUCCESS",
                "detail": "تم تسجيل الخروج بنجاح.",
            },
            status=status.HTTP_200_OK,
        )

        # نحذف Access وRefresh Cookies من المتصفح.
        delete_auth_cookies(response)

        return response


class WebMeView(APIView):
    """
    يرجع بيانات المستخدم الحالي اعتماداً
    على Access Token الموجود داخل Cookie.
    """

    # نحدد الكلاس الذي يقرأ JWT من Cookie.
    authentication_classes = [
        CookieJWTAuthentication,
    ]

    # يجب أن يكون المستخدم مسجل دخول
    # ومسموحاً له باستخدام Web Dashboard.
    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
    ]
    allow_password_change_required = True

    @extend_schema(
        responses={
            status.HTTP_200_OK: UserSummarySerializer,
        },
    )
    def get(self, request):
        return Response(
            {
                "code": "CURRENT_USER_RETRIEVED",
                "detail": "تم جلب بيانات المستخدم بنجاح.",
                **UserSummarySerializer(request.user).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=WebMeUpdateSerializer,
        responses={status.HTTP_200_OK: UserSummarySerializer},
        description="تحديث الاسم والبريد الإلكتروني للمستخدم الحالي فقط.",
    )
    def patch(self, request):
        serializer = WebMeUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "code": "PROFILE_UPDATED",
                "detail": "تم تحديث بيانات الحساب بنجاح.",
                **UserSummarySerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class WebChangePasswordView(APIView):
    allow_password_change_required = True
    permission_classes = [IsAuthenticated, IsWebDashboardUser]

    @extend_schema(
        request=ChangePasswordSerializer, responses={200: MessageResponseSerializer}
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        raw_refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if raw_refresh:
            from rest_framework_simplejwt.exceptions import TokenError
            from rest_framework_simplejwt.tokens import RefreshToken

            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass

        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        refresh["client"] = "web"
        refresh["token_version"] = user.token_version
        response = Response(
            {
                "code": "PASSWORD_CHANGED",
                "detail": "تم تغيير كلمة المرور بنجاح.",
            }
        )
        set_auth_cookies(
            response=response,
            access_token=str(refresh.access_token),
            refresh_token=str(refresh),
        )
        return response


class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    تعرض قائمة حسابات المستخدمين المسموح
    للمستخدم الحالي بالوصول إليها.

    تدعم:
    - Pagination
    - البحث
    - الفلترة
    - الترتيب
    - تقييد النتائج حسب دور المستخدم الحالي
    """

    permission_classes = [IsAuthenticated, IsWebDashboardUser, CanViewAccounts]
    http_method_names = ["get", "post", "patch", "head", "options"]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_fields = [
        "role",
        "is_active",
        "must_change_password",
    ]

    search_fields = [
        "username",
        "email",
        "first_name",
        "last_name",
    ]

    ordering_fields = [
        "username",
        "first_name",
        "last_name",
        "date_joined",
    ]

    ordering = [
        "-date_joined",
    ]

    serializer_action_classes = {
        "list": UserListSerializer,
        "retrieve": UserDetailSerializer,
        "create": UserCreateSerializer,
        "partial_update": UserUpdateSerializer,
        "set_active": SetUserActiveSerializer,
        "reset_password": ResetPasswordResponseSerializer,
    }

    def get_serializer_class(self):
        return self.serializer_action_classes.get(self.action, UserDetailSerializer)

    def get_queryset(self):
        """
        تعيد الحسابات الواقعة ضمن نطاق رؤية
        المستخدم الذي أرسل الطلب.
        """

        queryset = User.objects.all()

        return get_visible_accounts_queryset(
            self.request.user,
            queryset,
        )

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data = {
            "code": "USERS_RETRIEVED",
            "detail": "تم جلب قائمة المستخدمين بنجاح.",
            **response.data,
        }
        return response

    def retrieve(self, request, *args, **kwargs):
        user = self.get_object()
        return Response(
            {
                "code": "USER_RETRIEVED",
                "detail": "تم جلب بيانات المستخدم بنجاح.",
                **UserDetailSerializer(user).data,
            }
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "code": "USER_CREATED",
                "detail": "تم إنشاء الحساب بنجاح.",
                **UserCreateSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = self.get_serializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "code": "USER_UPDATED",
                "detail": "تم تحديث بيانات المستخدم بنجاح.",
                **UserDetailSerializer(user).data,
            }
        )

    @extend_schema(
        request=SetUserActiveSerializer,
        responses={status.HTTP_200_OK: UserDetailSerializer},
        description="تفعيل الحساب أو تعطيله. لا يمكن استخدام PATCH لتغيير هذه الحالة.",
    )
    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        user = self.get_object()
        if not can_set_account_active(request.user, user):
            raise PermissionDenied(
                {"code": "SET_ACTIVE_FORBIDDEN", "detail": "ليس لديك صلاحية لتغيير حالة هذا الحساب."}
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, changed = set_account_active(user, serializer.validated_data["is_active"])
        return Response(
            {
                "code": "USER_ACTIVE_STATUS_UPDATED" if changed else "USER_ACTIVE_STATUS_UNCHANGED",
                "detail": "تم تحديث حالة الحساب بنجاح." if changed else "الحساب مضبوط مسبقاً على الحالة المطلوبة.",
                **UserDetailSerializer(user).data,
            }
        )

    @extend_schema(
        request=None,
        responses={status.HTTP_200_OK: ResetPasswordResponseSerializer},
        description="إنشاء كلمة مرور مؤقتة جديدة وإعادتها مرة واحدة فقط.",
    )
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        if not can_reset_account_password(request.user, user):
            raise PermissionDenied(
                {"code": "PASSWORD_RESET_FORBIDDEN", "detail": "ليس لديك صلاحية لإعادة تعيين كلمة مرور هذا الحساب."}
            )
        _, password = reset_account_password(user)
        return Response(
            {
                "code": "PASSWORD_RESET",
                "detail": "تمت إعادة تعيين كلمة المرور بنجاح.",
                "temporary_password": password,
            }
        )
