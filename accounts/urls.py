from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.permission_views import PermissionCatalogView, UserPermissionsView
from accounts.views import UserViewSet


app_name = "accounts"

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("permissions/", PermissionCatalogView.as_view(), name="permission-catalog"),
    path(
        "users/<uuid:user_id>/permissions/",
        UserPermissionsView.as_view(),
        name="user-permissions",
    ),
    path("", include(router.urls)),
]
