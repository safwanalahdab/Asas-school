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
            # Without httpTimeout the SDK waits up to 120 seconds per request.
            options = {"httpTimeout": settings.FIREBASE_HTTP_TIMEOUT_SECONDS}
            if settings.FIREBASE_PROJECT_ID:
                options["projectId"] = settings.FIREBASE_PROJECT_ID
            _firebase_app = firebase_admin.initialize_app(options=options)
        return _firebase_app
