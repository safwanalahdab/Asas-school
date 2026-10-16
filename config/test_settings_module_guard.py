import json
import os
import subprocess
import sys

from django.test import SimpleTestCase

from config.test_production_settings import (
    BASE_DIR,
    MANAGED_ENVIRONMENT_VARIABLES,
    VALID_PRODUCTION_ENVIRONMENT,
)


SERVER_MODULES = ("config.wsgi", "config.asgi")

# Disables the local .env file, imports the entry point and prints JSON.
ENTRY_POINT_PROBE_SCRIPT = """
import importlib
import json
import sys

import environ

environ.Env.read_env = classmethod(lambda cls, *args, **kwargs: None)

from django.core.exceptions import ImproperlyConfigured

try:
    module = importlib.import_module(sys.argv[1])
except ImproperlyConfigured as error:
    print(json.dumps({"error": str(error)}))
    sys.exit(0)

print(json.dumps({
    "application": type(module.application).__name__,
    "callable": callable(module.application),
}))
"""


def import_entry_point(module_name, environment):
    process_environment = {
        key: value
        for key, value in os.environ.items()
        if key not in MANAGED_ENVIRONMENT_VARIABLES
    }
    process_environment.update(environment)

    completed = subprocess.run(
        [sys.executable, "-c", ENTRY_POINT_PROBE_SCRIPT, module_name],
        cwd=BASE_DIR,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"Entry point probe for {module_name} crashed:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


class SettingsModuleGuardTests(SimpleTestCase):
    def assert_refused(self, module_name, environment):
        result = import_entry_point(module_name, environment)
        self.assertIn("error", result, f"{module_name} started without settings.")
        # Django's own "settings are not configured" error also names the
        # variable, so check for this guard's message specifically.
        self.assertIn("DJANGO_SETTINGS_MODULE", result["error"])
        self.assertIn("config.production_settings", result["error"])
        self.assertIn("manage.py runserver", result["error"])

    def test_missing_settings_module_is_refused(self):
        for module_name in SERVER_MODULES:
            with self.subTest(module=module_name):
                self.assert_refused(module_name, VALID_PRODUCTION_ENVIRONMENT)

    def test_empty_settings_module_is_refused(self):
        for module_name in SERVER_MODULES:
            for value in ("", "   "):
                with self.subTest(module=module_name, value=value):
                    self.assert_refused(module_name, {
                        **VALID_PRODUCTION_ENVIRONMENT,
                        "DJANGO_SETTINGS_MODULE": value,
                    })

    def test_explicit_settings_module_starts_the_application(self):
        expected = {"config.wsgi": "WSGIHandler", "config.asgi": "ASGIHandler"}
        for module_name in SERVER_MODULES:
            with self.subTest(module=module_name):
                result = import_entry_point(module_name, {
                    **VALID_PRODUCTION_ENVIRONMENT,
                    "DJANGO_SETTINGS_MODULE": "config.production_settings",
                })
                self.assertNotIn("error", result, result.get("error"))
                self.assertEqual(result["application"], expected[module_name])
                self.assertIs(result["callable"], True)
