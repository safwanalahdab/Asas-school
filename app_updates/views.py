from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api_responses import ArabicApiResponseMixin

from .models import AppUpdatePolicy
from .serializers import (
    AppUpdateCheckQuerySerializer,
    AppUpdateCheckResponseSerializer,
)


def build_update_check_result(*, platform, current_build):
    policy = AppUpdatePolicy.objects.filter(platform=platform).first()
    if policy is None:
        # Fail-open: غياب الإعداد لا يمنع المستخدم من متابعة التطبيق.
        return {
            "platform": platform,
            "check_enabled": False,
            "latest_version": None,
            "latest_build": None,
            "minimum_supported_build": None,
            "update_available": False,
            "force_update": False,
            "update_message": "",
            "store_url": None,
        }

    update_available, force_update = policy.evaluate(current_build)
    return {
        "platform": policy.platform,
        "check_enabled": policy.is_check_enabled,
        "latest_version": policy.latest_version,
        "latest_build": policy.latest_build,
        "minimum_supported_build": policy.minimum_supported_build,
        "update_available": update_available,
        "force_update": force_update,
        "update_message": policy.update_message,
        "store_url": policy.store_url,
    }


class AppUpdateCheckView(ArabicApiResponseMixin, APIView):
    """
    يحدد للتطبيق هل يوجد تحديث وهل هو إجباري.
    يعمل قبل تسجيل الدخول، لذلك المصادقة معطلة على هذا المسار.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        parameters=[AppUpdateCheckQuerySerializer],
        responses={200: AppUpdateCheckResponseSerializer},
        description=(
            "فحص توفر تحديث لتطبيق أساس. القرار يعتمد على رقم Build فقط، "
            "والتحديث نفسه يتم من المتجر الرسمي."
        ),
    )
    def get(self, request):
        query = AppUpdateCheckQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        return Response(
            {
                "code": "MOBILE_APP_UPDATE_CHECKED",
                "detail": "تم التحقق من إصدار التطبيق بنجاح.",
                "data": build_update_check_result(
                    platform=params["platform"],
                    current_build=params["current_build"],
                ),
            }
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        # لا يحتفظ Proxy أو التطبيق بقرار قديم بعد تعديل السياسة.
        response["Cache-Control"] = "no-store"
        return response
