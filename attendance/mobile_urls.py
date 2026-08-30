from django.urls import path

from .mobile_views import MobileChildAttendanceHistoryView, MobileChildTodayAttendanceView

app_name = "attendance-mobile"

urlpatterns = [
    path("", MobileChildAttendanceHistoryView.as_view(), name="child-attendance-history"),
    path("today/", MobileChildTodayAttendanceView.as_view(), name="child-attendance-today"),
]
