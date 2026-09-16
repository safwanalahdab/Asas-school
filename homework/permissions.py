from rest_framework.permissions import BasePermission


class IsWebClientToken(BasePermission):
    """Preserve the web-token gate without using role for action authorization."""

    message = "هذه الواجهة تتطلب جلسة ويب."

    def has_permission(self, request, view):
        token = request.auth
        return token is not None and token.get("client") == "web"
