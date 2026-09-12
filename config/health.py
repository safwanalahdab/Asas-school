import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_safe


logger = logging.getLogger(__name__)


@require_safe
def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError as exc:
        logger.warning(
            "Health check database probe failed: %s",
            type(exc).__name__,
        )
        return JsonResponse(
            {
                "success": False,
                "code": "HEALTH_CHECK_FAILED",
                "message": "الخدمة غير جاهزة حالياً.",
                "data": {"status": "unhealthy"},
            },
            status=503,
        )

    return JsonResponse(
        {
            "success": True,
            "code": "HEALTH_CHECK_OK",
            "message": "الخدمة تعمل بشكل طبيعي.",
            "data": {"status": "healthy"},
        }
    )
