import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from config.attachment_validation import (
    MAX_ATTACHMENT_SIZE,
    validate_attachment,
)


class AttachmentValidationTests(SimpleTestCase):
    def image_bytes(self, image_format):
        stream = io.BytesIO()
        Image.new("RGB", (2, 2), color="white").save(stream, format=image_format)
        return stream.getvalue()

    def upload(self, name, content, content_type=None):
        return SimpleUploadedFile(name, content, content_type=content_type)

    def assert_rejected(self, uploaded_file):
        with self.assertRaises(ValidationError):
            validate_attachment(uploaded_file)

    def test_valid_jpeg_is_accepted_case_insensitively(self):
        validate_attachment(
            self.upload("photo.JPEG", self.image_bytes("JPEG"), "image/jpeg")
        )

    def test_valid_png_is_accepted(self):
        validate_attachment(
            self.upload("image.png", self.image_bytes("PNG"), "image/png")
        )

    def test_valid_minimal_pdf_is_accepted(self):
        content = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"xref\n0 1\n0000000000 65535 f \n"
            b"trailer\n<< /Root 1 0 R /Size 1 >>\n"
            b"startxref\n45\n%%EOF\n"
        )
        validate_attachment(self.upload("document.pdf", content, "application/pdf"))

    def test_file_over_five_megabytes_is_rejected(self):
        self.assert_rejected(
            self.upload(
                "large.pdf",
                b"%PDF-1.4\n" + b"x" * MAX_ATTACHMENT_SIZE,
                "application/pdf",
            )
        )

    def test_forbidden_extension_is_rejected(self):
        self.assert_rejected(self.upload("malware.exe", b"content"))

    def test_missing_extension_is_rejected(self):
        self.assert_rejected(self.upload("attachment", b"content"))

    def test_fake_jpg_containing_text_is_rejected(self):
        self.assert_rejected(self.upload("fake.jpg", b"plain text", "image/jpeg"))

    def test_fake_png_containing_text_is_rejected(self):
        self.assert_rejected(self.upload("fake.png", b"plain text", "image/png"))

    def test_fake_pdf_containing_text_is_rejected(self):
        self.assert_rejected(
            self.upload("fake.pdf", b"plain text", "application/pdf")
        )

    def test_png_content_named_jpg_is_rejected(self):
        self.assert_rejected(
            self.upload("wrong.jpg", self.image_bytes("PNG"), "image/jpeg")
        )

    def test_jpeg_content_named_png_is_rejected(self):
        self.assert_rejected(
            self.upload("wrong.png", self.image_bytes("JPEG"), "image/png")
        )

    def test_obviously_inconsistent_content_type_is_rejected(self):
        self.assert_rejected(
            self.upload("image.png", self.image_bytes("PNG"), "text/plain")
        )

    def test_success_restores_stream_position(self):
        content = self.image_bytes("PNG")
        uploaded_file = self.upload("image.png", content, "image/png")

        validate_attachment(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)
        self.assertEqual(uploaded_file.read(), content)

    def test_failure_restores_stream_position(self):
        uploaded_file = self.upload("fake.png", b"plain text", "image/png")

        self.assert_rejected(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)
        self.assertEqual(uploaded_file.read(), b"plain text")
