from django.urls import path

from .mobile_views import MobileChildGradesView

app_name = "grades-mobile"

urlpatterns = [path("", MobileChildGradesView.as_view(), name="child-grades")]
