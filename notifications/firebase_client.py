import threading

from django.conf import settings


_initialization_lock = threading.Lock()
_firebase_app = None


def get_firebase_app():
    """Lazily initialize one Firebase app using Application Default Credentials."""
    global _firebase_app
    if not settings.FIREBASE_PUSH_ENABLED:
        return None
    if _firebase_app is not None:
        return _firebase_app

    with _initialization_lock:
        if _firebase_app is not None:
            return _firebase_app

        import firebase_admin

        try:
            _firebase_app = firebase_admin.get_app()
        except ValueError:
            options = (
                {"projectId": settings.FIREBASE_PROJECT_ID}
                if settings.FIREBASE_PROJECT_ID
                else None
            )
            _firebase_app = firebase_admin.initialize_app(options=options)
        return _firebase_app
