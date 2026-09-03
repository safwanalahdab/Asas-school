from django.urls import path

from .mobile_views import (
    MobilePushDeviceRegistrationView,
    MobilePushDeviceUnregisterView,
)


app_name = "mobile-devices"

urlpatterns = [
    path("", MobilePushDeviceRegistrationView.as_view(), name="register"),
    path(
        "unregister/",
        MobilePushDeviceUnregisterView.as_view(),
        name="unregister",
    ),
]
