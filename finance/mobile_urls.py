from django.urls import path

from .mobile_views import MobileChildFinanceView

app_name = "finance-mobile"

urlpatterns = [path("", MobileChildFinanceView.as_view(), name="child-finance")]
