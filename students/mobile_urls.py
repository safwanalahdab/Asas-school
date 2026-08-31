from django.urls import include, path

from .mobile_views import (
    MobileChildDetailView,
    MobileChildrenListView,
)


app_name = "students-mobile"


urlpatterns = [
    path(
        "requests/",
        include("school_requests.mobile_urls"),
    ),
    path(
        "children/",
        MobileChildrenListView.as_view(),
        name="children-list",
    ),
    path(
        "children/<uuid:student_id>/",
        MobileChildDetailView.as_view(),
        name="children-detail",
    ),
    path(
        "children/<uuid:student_id>/homework/",
        include("homework.mobile_urls"),
    ),
    path(
        "children/<uuid:student_id>/announcements/",
        include("announcements.mobile_urls"),
    ),
    path(
        "children/<uuid:student_id>/grades/",
        include("grades.mobile_urls"),
    ),
    path(
        "children/<uuid:student_id>/attendance/",
        include("attendance.mobile_urls"),
    ),
    path(
        "children/<uuid:student_id>/behavior/",
        include("behavior.mobile_urls"),
    ),
    path(
        "children/<uuid:student_id>/finance/",
        include("finance.mobile_urls"),
    ),
]
