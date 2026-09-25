from django.urls import path

from .mobile_views import MobileChildPointsView


app_name = "behavior-mobile-points"


urlpatterns = [
    path("", MobileChildPointsView.as_view(), name="child-points"),
]
