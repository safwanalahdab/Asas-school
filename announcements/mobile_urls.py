from django.urls import path

from .mobile_views import MobileChildAnnouncementsView

app_name = "announcements-mobile"

urlpatterns = [
    path("", MobileChildAnnouncementsView.as_view(), name="child-announcements")
]
