"""Settings selection guard for the WSGI and ASGI entry points.

Unlike ``manage.py``, the server entry points have no default settings
module: a missing value must stop the server instead of silently starting it
with the development settings.
"""

import os

from django.core.exceptions import ImproperlyConfigured


def require_settings_module():
    if not os.environ.get("DJANGO_SETTINGS_MODULE", "").strip():
        raise ImproperlyConfigured(
            "DJANGO_SETTINGS_MODULE is required to start the WSGI/ASGI "
            "application. In production set "
            "DJANGO_SETTINGS_MODULE=config.production_settings. For local "
            "development use `python manage.py runserver`."
        )
