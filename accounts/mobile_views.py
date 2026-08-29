from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from accounts.mobile_serializers import (
    MobileGuardianSerializer,
    MobileChangePasswordResponseSerializer,
    MobileLoginResponseSerializer,
    MobileLoginSerializer,
    MobileLogoutSerializer,
    MobileLogoutResponseSerializer,
    MobileMeResponseSerializer,
    MobileRefreshResponseSerializer,
    MobileTokenRefreshSerializer,
)
from accounts.serializers import ChangePasswordSerializer
from accounts.throttles import MobileLoginRateThrottle
from config.api_responses import ArabicApiResponseMixin


class MobileLoginView(ArabicApiResponseMixin, APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [MobileLoginRateThrottle]

    @extend_schema(request=MobileLoginSerializer, responses={200: MobileLoginResponseSerializer})
    def post(self, request):
        serializer = MobileLoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response({
            "code": "MOBILE_LOGIN_SUCCESS",
            "detail": "تم تسجيل الدخول بنجاح.",
            "access": data["access"],
            "refresh": data["refresh"],
            "user": MobileGuardianSerializer(data["user"]).data,
        })


class MobileTokenRefreshView(ArabicApiResponseMixin, APIView):
    authentication_classes = []
    permission_classes = []
    allow_password_change_required = True

    @extend_schema(request=MobileTokenRefreshSerializer, responses={200: MobileRefreshResponseSerializer})
    def post(self, request):
        serializer = MobileTokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({
            "code": "MOBILE_SESSION_REFRESHED",
            "detail": "تم تجديد الجلسة بنجاح.",
            **serializer.validated_data,
        })


class MobileLogoutView(ArabicApiResponseMixin, APIView):
    authentication_classes = []
    permission_classes = []
    allow_password_change_required = True

    @extend_schema(request=MobileLogoutSerializer, responses={200: MobileLogoutResponseSerializer})
    def post(self, request):
        serializer = MobileLogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            "code": "MOBILE_LOGOUT_SUCCESS", "detail": "تم تسجيل الخروج بنجاح."
        })


class MobileMeView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]
    allow_password_change_required = True

    @extend_schema(responses={200: MobileMeResponseSerializer})
    def get(self, request):
        return Response({
            "code": "MOBILE_CURRENT_USER_RETRIEVED",
            "detail": "تم جلب بيانات المستخدم بنجاح.",
            **MobileGuardianSerializer(request.user).data,
        })


class MobileChangePasswordView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]
    allow_password_change_required = True

    @extend_schema(request=ChangePasswordSerializer, responses={200: MobileChangePasswordResponseSerializer})
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            "code": "MOBILE_PASSWORD_CHANGED",
            "detail": "تم تغيير كلمة المرور بنجاح. يرجى تسجيل الدخول من جديد.",
        }, status=status.HTTP_200_OK)
