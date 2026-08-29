from django.urls import path

from accounts.mobile_views import (
    MobileChangePasswordView,
    MobileLoginView,
    MobileLogoutView,
    MobileMeView,
    MobileTokenRefreshView,
)

app_name = "mobile_auth"

urlpatterns = [
    path("login/", MobileLoginView.as_view(), name="login"),
    path("refresh/", MobileTokenRefreshView.as_view(), name="refresh"),
    path("logout/", MobileLogoutView.as_view(), name="logout"),
    path("me/", MobileMeView.as_view(), name="me"),
    path("change-password/", MobileChangePasswordView.as_view(), name="change-password"),
]
