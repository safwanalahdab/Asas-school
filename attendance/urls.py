from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import AttendanceRecordViewSet, AttendanceSheetViewSet
router = DefaultRouter()
router.register("sheets", AttendanceSheetViewSet, basename="attendance-sheet")
router.register("records", AttendanceRecordViewSet, basename="attendance-record")
urlpatterns = [path("", include(router.urls))]
