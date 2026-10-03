from django.urls import path

from .mobile_views import MobileChildExamsView

app_name = "grades-mobile-exams"

urlpatterns = [path("", MobileChildExamsView.as_view(), name="child-exams")]
