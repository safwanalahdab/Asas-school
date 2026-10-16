from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class WebLoginRateThrottle(AnonRateThrottle):
    """
    تحد عدد محاولات تسجيل الدخول للزوار غير المسجلين.
    """

    scope = "web_login"


class MobileLoginRateThrottle(AnonRateThrottle):
    """Rate limit Guardian mobile login attempts independently from Web login."""

    scope = "mobile_login"


class MobileAccountDeletionThrottle(UserRateThrottle):
    """Limit password guesses through the Guardian account deletion endpoint."""

    scope = "mobile_account_deletion"
