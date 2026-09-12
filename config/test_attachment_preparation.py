import io
from dataclasses import FrozenInstanceError
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from config.attachment_preparation import prepare_attachment
from config.attachment_validation import MAX_ATTACHMENT_SIZE


class AttachmentPreparationTests(SimpleTestCase):
    def image_bytes(self, image_format):
        stream = io.BytesIO()
        mode = "RGB" if image_format == "JPEG" else "RGBA"
        color = "red" if mode == "RGB" else (255, 0, 0, 128)
        Image.new(mode, (20, 10), color=color).save(
            stream,
            format=image_format,
        )
        return stream.getvalue()

    def upload(self, name, content, content_type):
        return SimpleUploadedFile(name, content, content_type=content_type)

    def minimal_pdf(self):
        return (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"xref\n0 1\n0000000000 65535 f \n"
            b"trailer\n<< /Root 1 0 R /Size 1 >>\n"
            b"startxref\n45\n%%EOF\n"
        )

    def assert_uuid4_filename(self, filename, extension):
        self.assertTrue(filename.endswith(extension))
        identifier = UUID(filename.removesuffix(extension))
        self.assertEqual(identifier.version, 4)
        self.assertEqual(filename, f"{identifier}{extension}")

    def test_jpeg_produces_webp_content_and_identity(self):
        uploaded_file = self.upload(
            "photo.jpg",
            self.image_bytes("JPEG"),
            "image/jpeg",
        )

        prepared = prepare_attachment(uploaded_file)

        self.assert_uuid4_filename(prepared.filename, ".webp")
        self.assertEqual(prepared.content_type, "image/webp")
        with Image.open(io.BytesIO(prepared.content)) as image:
            self.assertEqual(image.format, "WEBP")

    def test_png_produces_webp_content_and_identity(self):
        prepared = prepare_attachment(
            self.upload("image.png", self.image_bytes("PNG"), "image/png")
        )

        self.assert_uuid4_filename(prepared.filename, ".webp")
        self.assertEqual(prepared.content_type, "image/webp")
        with Image.open(io.BytesIO(prepared.content)) as image:
            self.assertEqual(image.format, "WEBP")

    def test_pdf_content_is_unchanged(self):
        content = self.minimal_pdf()

        prepared = prepare_attachment(
            self.upload("document.pdf", content, "application/pdf")
        )

        self.assertEqual(prepared.content, content)
        self.assert_uuid4_filename(prepared.filename, ".pdf")
        self.assertEqual(prepared.content_type, "application/pdf")

    def test_original_filename_is_not_reused(self):
        prepared = prepare_attachment(
            self.upload(
                "واجب أحمد.jpg",
                self.image_bytes("JPEG"),
                "image/jpeg",
            )
        )

        self.assertNotIn("واجب", prepared.filename)
        self.assertNotIn("أحمد", prepared.filename)

    def test_same_original_filename_generates_distinct_names(self):
        content = self.image_bytes("PNG")

        first = prepare_attachment(self.upload("same.png", content, "image/png"))
        second = prepare_attachment(self.upload("same.png", content, "image/png"))

        self.assertNotEqual(first.filename, second.filename)

    def test_uppercase_extensions_are_supported(self):
        image = prepare_attachment(
            self.upload("IMAGE.JPEG", self.image_bytes("JPEG"), "image/jpeg")
        )
        pdf = prepare_attachment(
            self.upload("DOCUMENT.PDF", self.minimal_pdf(), "application/pdf")
        )

        self.assertTrue(image.filename.endswith(".webp"))
        self.assertTrue(pdf.filename.endswith(".pdf"))

    def test_fake_image_is_rejected_by_existing_validation(self):
        with self.assertRaises(ValidationError):
            prepare_attachment(self.upload("fake.jpg", b"text", "image/jpeg"))

    def test_fake_pdf_is_rejected_by_existing_validation(self):
        with self.assertRaises(ValidationError):
            prepare_attachment(
                self.upload("fake.pdf", b"plain text", "application/pdf")
            )

    def test_file_over_five_megabytes_is_rejected(self):
        content = b"%PDF-1.4\n" + b"x" * MAX_ATTACHMENT_SIZE

        with self.assertRaises(ValidationError):
            prepare_attachment(
                self.upload("large.pdf", content, "application/pdf")
            )

    def test_image_success_restores_source_stream(self):
        content = self.image_bytes("PNG")
        uploaded_file = self.upload("image.png", content, "image/png")

        prepare_attachment(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)
        self.assertEqual(uploaded_file.read(), content)

    def test_pdf_success_restores_source_stream(self):
        content = self.minimal_pdf()
        uploaded_file = self.upload("document.pdf", content, "application/pdf")

        prepare_attachment(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)
        self.assertEqual(uploaded_file.read(), content)

    def test_failure_restores_source_stream(self):
        content = b"plain text"
        uploaded_file = self.upload("fake.png", content, "image/png")

        with self.assertRaises(ValidationError):
            prepare_attachment(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)
        self.assertEqual(uploaded_file.read(), content)

    def test_original_path_information_is_not_used(self):
        prepared = prepare_attachment(
            self.upload(
                "../../secret.jpg",
                self.image_bytes("JPEG"),
                "image/jpeg",
            )
        )

        self.assertNotIn("secret", prepared.filename)
        self.assertNotIn("/", prepared.filename)
        self.assertNotIn("\\", prepared.filename)
        self.assert_uuid4_filename(prepared.filename, ".webp")

    def test_prepared_result_is_immutable(self):
        prepared = prepare_attachment(
            self.upload("image.png", self.image_bytes("PNG"), "image/png")
        )

        with self.assertRaises(FrozenInstanceError):
            prepared.filename = "changed.webp"
