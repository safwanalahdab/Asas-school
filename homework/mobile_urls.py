from django.urls import path

from .mobile_views import MobileChildHomeworkView

app_name = "homework-mobile"

urlpatterns = [path("", MobileChildHomeworkView.as_view(), name="child-homework")]
