from rest_framework.throttling import AnonRateThrottle


class WebLoginRateThrottle(AnonRateThrottle):
    """
    تحد عدد محاولات تسجيل الدخول للزوار غير المسجلين.
    """

    scope = "web_login"


class MobileLoginRateThrottle(AnonRateThrottle):
    """Rate limit Guardian mobile login attempts independently from Web login."""

    scope = "mobile_login"

