"""Shared attachment lifecycle tests for API resources with an ``attachment``.

Not a test module itself: concrete ``TestCase`` classes in each app mix this
in and provide the resource-specific hooks listed on the class.
"""
import io
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import override_settings
from PIL import Image
from rest_framework.serializers import ModelSerializer

from config import attachment_serializers
from config.attachment_processing import IMAGE_PIXEL_LIMIT_ERROR
from config.attachment_storage import delete_attachment_on_commit


MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f \n"
    b"trailer\n<< /Root 1 0 R /Size 1 >>\n"
    b"startxref\n45\n%%EOF\n"
)


class AttachmentLifecycleTestsMixin:
    """Subclasses define:

    - ``model``, ``list_url``, ``upload_dir`` and ``notify_path`` (the
      create-time notification called inside the view's transaction);
    - ``create_payload()`` returning valid create fields without attachment;
    - ``create_existing(attachment)`` saving an instance directly via the ORM.
    """

    model = None
    list_url = None
    upload_dir = None
    notify_path = None

    def setUp(self):
        super().setUp()
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media.name)
        media_override.enable()
        self.addCleanup(media_override.disable)

    # Helpers

    def stored_files(self):
        root = Path(self.media.name) / self.upload_dir
        return sorted(path.name for path in root.glob("*")) if root.exists() else []

    def image_upload(self, name="photo.png"):
        stream = io.BytesIO()
        Image.new("RGB", (40, 20), "red").save(stream, format="PNG")
        return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")

    def pdf_upload(self, name="report.pdf"):
        return SimpleUploadedFile(name, MINIMAL_PDF, content_type="application/pdf")

    def detail_url(self, obj):
        return f"{self.list_url}{obj.pk}/"

    def create(self, attachment):
        return self.client.post(
            self.list_url,
            {**self.create_payload(), "attachment": attachment},
            format="multipart",
        )

    def create_with_file(self, attachment=None):
        response = self.create(attachment or self.image_upload())
        self.assertEqual(response.status_code, 201, response.data)
        return self.model.objects.get(pk=response.data["data"]["id"])

    def assert_uuid_name(self, stored_name, extension):
        path = Path(stored_name)
        self.assertEqual(path.parent.as_posix(), self.upload_dir)
        self.assertEqual(path.suffix, extension)
        self.assertEqual(UUID(path.stem).version, 4)

    def fail_after_update(self):
        original_update = ModelSerializer.update

        def update_then_fail(serializer, instance, validated_data):
            original_update(serializer, instance, validated_data)
            raise RuntimeError("database failure after the new file was stored")

        return patch.object(ModelSerializer, "update", update_then_fail)

    # 1. Invalid uploads

    def test_oversized_image_is_rejected_without_storing_a_file(self):
        with patch(
            "config.attachment_preparation.optimize_validated_image_content",
            side_effect=ValidationError(IMAGE_PIXEL_LIMIT_ERROR),
        ):
            response = self.create(self.image_upload("oversized.png"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("attachment", response.data["errors"])
        self.assertIn(
            IMAGE_PIXEL_LIMIT_ERROR,
            str(response.data["errors"]["attachment"]),
        )
        self.assertEqual(self.model.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_invalid_upload_is_rejected_and_stores_nothing(self):
        before = self.model.objects.count()

        response = self.create(
            SimpleUploadedFile("fake.png", b"not an image", content_type="image/png"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("attachment", response.data["errors"])
        self.assertRegex(str(response.data["errors"]["attachment"]), "[؀-ۿ]")
        self.assertEqual(self.model.objects.count(), before)
        self.assertEqual(self.stored_files(), [])

    def test_disallowed_extension_is_rejected_and_stores_nothing(self):
        response = self.create(
            SimpleUploadedFile("notes.txt", b"plain text", content_type="text/plain"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("attachment", response.data["errors"])
        self.assertEqual(self.stored_files(), [])

    # 2-3. Normalized storage names

    def test_image_upload_is_stored_as_uuid_webp(self):
        obj = self.create_with_file(self.image_upload("class photo.png"))

        self.assert_uuid_name(obj.attachment.name, ".webp")
        with obj.attachment.open("rb") as stored, Image.open(stored) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (40, 20))
        self.assertEqual(self.stored_files(), [Path(obj.attachment.name).name])

    def test_pdf_upload_stays_pdf_with_uuid_name(self):
        obj = self.create_with_file(self.pdf_upload("لائحة.pdf"))

        self.assert_uuid_name(obj.attachment.name, ".pdf")
        with obj.attachment.open("rb") as stored:
            self.assertEqual(stored.read(), MINIMAL_PDF)

    # 4. Failed create

    def test_failed_create_leaves_no_file_or_row(self):
        before = self.model.objects.count()

        with patch(self.notify_path, side_effect=RuntimeError("notify failed")):
            response = self.create(self.image_upload())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.model.objects.count(), before)
        self.assertEqual(self.stored_files(), [])

    # 5. Failed update

    def test_failed_replace_keeps_old_file_and_discards_new(self):
        obj = self.create_with_file()
        original_name = obj.attachment.name

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.fail_after_update():
                response = self.client.patch(
                    self.detail_url(obj),
                    {"attachment": self.image_upload("replacement.png")},
                    format="multipart",
                )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(callbacks, [])
        obj.refresh_from_db()
        self.assertEqual(obj.attachment.name, original_name)
        self.assertEqual(self.stored_files(), [Path(original_name).name])

    def test_failed_clear_keeps_old_file_and_reference(self):
        obj = self.create_with_file()
        original_name = obj.attachment.name

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.fail_after_update():
                response = self.client.patch(self.detail_url(obj), {"attachment": None}, format="json")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(callbacks, [])
        obj.refresh_from_db()
        self.assertEqual(obj.attachment.name, original_name)
        self.assertEqual(self.stored_files(), [Path(original_name).name])

    # 6. Successful replace

    def test_successful_replace_deletes_old_file_only_after_commit(self):
        obj = self.create_with_file()
        original_name = obj.attachment.name

        with self.captureOnCommitCallbacks() as callbacks:
            response = self.client.patch(
                self.detail_url(obj),
                {"attachment": self.pdf_upload("replacement.pdf")},
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        new_name = obj.attachment.name
        self.assertNotEqual(new_name, original_name)
        self.assert_uuid_name(new_name, ".pdf")
        # Before commit both files exist; the old one goes only on commit.
        self.assertEqual(
            self.stored_files(), sorted([Path(original_name).name, Path(new_name).name]),
        )

        for callback in callbacks:
            callback()

        self.assertEqual(self.stored_files(), [Path(new_name).name])

    # 7. attachment=null

    def test_null_clears_reference_and_deletes_old_file_after_commit(self):
        obj = self.create_with_file()
        original_name = obj.attachment.name

        with self.captureOnCommitCallbacks() as callbacks:
            response = self.client.patch(self.detail_url(obj), {"attachment": None}, format="json")

        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertFalse(obj.attachment)
        self.assertEqual(self.stored_files(), [Path(original_name).name])

        for callback in callbacks:
            callback()

        self.assertEqual(self.stored_files(), [])

    # 8. Delete

    def test_delete_removes_row_then_file_after_commit(self):
        obj = self.create_with_file()
        stored_name = Path(obj.attachment.name).name

        with self.captureOnCommitCallbacks() as callbacks:
            response = self.client.delete(self.detail_url(obj))

        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(self.model.objects.filter(pk=obj.pk).exists())
        self.assertEqual(self.stored_files(), [stored_name])

        for callback in callbacks:
            callback()

        self.assertEqual(self.stored_files(), [])

    # 9. Rollback

    def test_rollback_discards_scheduled_deletion(self):
        obj = self.create_with_file()
        stored_name = obj.attachment.name

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                delete_attachment_on_commit(self.model, stored_name)
                raise RuntimeError("rolled back")

        self.assertEqual(callbacks, [])
        self.assertEqual(self.stored_files(), [Path(stored_name).name])

    def test_failed_delete_keeps_row_and_file(self):
        obj = self.create_with_file()
        stored_name = Path(obj.attachment.name).name

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with patch.object(
                self.model, "delete", side_effect=RuntimeError("delete failed"),
            ):
                response = self.client.delete(self.detail_url(obj))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(callbacks, [])
        self.assertTrue(self.model.objects.filter(pk=obj.pk).exists())
        self.assertEqual(self.stored_files(), [stored_name])

    # 10. Storage delete failure

    def test_storage_delete_failure_is_logged_without_failing_request(self):
        obj = self.create_with_file()
        stored_name = obj.attachment.name

        with patch.object(
            FileSystemStorage, "delete", side_effect=OSError("storage unavailable"),
        ), self.assertLogs("config.attachment_storage", "WARNING") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    self.detail_url(obj),
                    {"attachment": self.image_upload("replacement.png")},
                    format="multipart",
                )

        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertNotEqual(obj.attachment.name, stored_name)
        self.assertIn(Path(stored_name).name, self.stored_files())
        output = "\n".join(logs.output)
        self.assertIn("OSError", output)
        self.assertNotIn(Path(stored_name).stem, output)
        self.assertNotIn("storage unavailable", output)

    def test_storage_delete_failure_on_destroy_does_not_fail_request(self):
        obj = self.create_with_file()

        with patch.object(
            FileSystemStorage, "delete", side_effect=OSError("storage unavailable"),
        ), self.assertLogs("config.attachment_storage", "WARNING"):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.delete(self.detail_url(obj))

        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(self.model.objects.filter(pk=obj.pk).exists())

    # 11. Existing files are left alone

    def test_existing_file_is_not_reprocessed_when_editing_other_fields(self):
        legacy_content = b"legacy bytes stored before the attachment policy"
        obj = self.create_existing(ContentFile(legacy_content, name="legacy-report.png"))
        legacy_name = obj.attachment.name

        with patch.object(
            attachment_serializers, "prepare_attachment",
            wraps=attachment_serializers.prepare_attachment,
        ) as prepare, self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.patch(
                self.detail_url(obj), {"title": "Edited title"}, format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        prepare.assert_not_called()
        self.assertEqual(callbacks, [])
        obj.refresh_from_db()
        self.assertEqual(obj.title, "Edited title")
        self.assertEqual(obj.attachment.name, legacy_name)
        with obj.attachment.open("rb") as stored:
            self.assertEqual(stored.read(), legacy_content)
        self.assertTrue(re.search(r"legacy-report.*\.png$", legacy_name))
