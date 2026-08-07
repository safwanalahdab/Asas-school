from django.conf import settings
from rest_framework_simplejwt.settings import api_settings


def set_auth_cookies(
    response,
    access_token,
    refresh_token,
):
    """
    يضع Access وRefresh Token داخل HttpOnly Cookies.
    """

    response.set_cookie(
        key=settings.JWT_ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=int(
            api_settings.ACCESS_TOKEN_LIFETIME.total_seconds()
        ),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path=settings.JWT_ACCESS_COOKIE_PATH,
        domain=settings.JWT_COOKIE_DOMAIN,
    )

    response.set_cookie(
        key=settings.JWT_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=int(
            api_settings.REFRESH_TOKEN_LIFETIME.total_seconds()
        ),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path=settings.JWT_REFRESH_COOKIE_PATH,
        domain=settings.JWT_COOKIE_DOMAIN,
    )


def delete_auth_cookies(response):
    """
    يحذف Cookies الخاصة بالمصادقة.
    """

    response.delete_cookie(
        key=settings.JWT_ACCESS_COOKIE_NAME,
        path=settings.JWT_ACCESS_COOKIE_PATH,
        domain=settings.JWT_COOKIE_DOMAIN,
        samesite=settings.JWT_COOKIE_SAMESITE,
    )

    response.delete_cookie(
        key=settings.JWT_REFRESH_COOKIE_NAME,
        path=settings.JWT_REFRESH_COOKIE_PATH,
        domain=settings.JWT_COOKIE_DOMAIN,
        samesite=settings.JWT_COOKIE_SAMESITE,
    )