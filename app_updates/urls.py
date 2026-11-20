from django.urls import path

from .views import AppUpdateCheckView


app_name = "app-updates"


urlpatterns = [
    path(
        "",
        AppUpdateCheckView.as_view(),
        name="check",
    ),
]
