from django.urls import path

from .mobile_views import MobileChildBehaviorView

app_name = "behavior-mobile"

urlpatterns = [path("", MobileChildBehaviorView.as_view(), name="child-behavior")]
