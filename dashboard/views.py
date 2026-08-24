from drf_spectacular.utils import extend_schema

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import PasswordChangeGate
from config.api_responses import ArabicApiResponseMixin

from .permissions import CanViewDashboardOverview
from .serializers import (
    DashboardOverviewQuerySerializer,
    DashboardOverviewSerializer,
)
from .services import get_dashboard_overview


class DashboardOverviewView(
    ArabicApiResponseMixin,
    APIView,
):
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        CanViewDashboardOverview,
    ]

    response_messages = {
        "get": (
            "DASHBOARD_OVERVIEW_RETRIEVED",
            "تم جلب إحصائيات لوحة التحكم بنجاح.",
        ),
    }

    @extend_schema(
        parameters=[
            DashboardOverviewQuerySerializer,
        ],
        responses={
            200: DashboardOverviewSerializer,
        },
    )
    def get(
        self,
        request,
    ):
        query_serializer = (
            DashboardOverviewQuerySerializer(
                data=request.query_params,
            )
        )

        query_serializer.is_valid(
            raise_exception=True,
        )

        filters = (
            query_serializer.validated_data
        )

        overview = get_dashboard_overview(
            academic_year=filters.get(
                "academic_year",
            ),
            grade_level=filters.get(
                "grade_level",
            ),
            section=filters.get(
                "section",
            ),
        )

        response_serializer = (
            DashboardOverviewSerializer(
                overview,
            )
        )

        return Response(
            response_serializer.data,
        )