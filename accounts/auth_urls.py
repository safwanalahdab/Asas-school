from django.urls import path

from accounts.views import (
    WebChangePasswordView,
    WebCsrfView,
    WebLoginView,
    WebLogoutView,
    WebMeView,
    WebTokenRefreshView,
)


app_name = "accounts_auth"

urlpatterns = [
    path("web/csrf/", WebCsrfView.as_view(), name="web-csrf"),
    path("web/login/", WebLoginView.as_view(), name="web-login"),
    path("web/refresh/", WebTokenRefreshView.as_view(), name="web-refresh"),
    path("web/logout/", WebLogoutView.as_view(), name="web-logout"),
    path("web/me/", WebMeView.as_view(), name="web-me"),
    path(
        "web/change-password/",
        WebChangePasswordView.as_view(),
        name="web-change-password",
    ),
]
