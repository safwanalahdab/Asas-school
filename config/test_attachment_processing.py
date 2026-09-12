import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image, features

from config.attachment_processing import (
    MAX_IMAGE_DIMENSION,
    WEBP_QUALITY,
    optimize_image_attachment,
)


class AttachmentProcessingTests(SimpleTestCase):
    def image_bytes(self, image_format, size, mode="RGB", exif=None):
        stream = io.BytesIO()
        color = (255, 0, 0, 0) if mode == "RGBA" else "red"
        image = Image.new(mode, size, color=color)
        save_options = {"format": image_format}
        if exif is not None:
            save_options["exif"] = exif
        image.save(stream, **save_options)
        return stream.getvalue()

    def upload(self, name, content, content_type):
        return SimpleUploadedFile(name, content, content_type=content_type)

    def process_image(self, name, image_format, size, mode="RGB", exif=None):
        content_type = "image/jpeg" if image_format == "JPEG" else "image/png"
        uploaded_file = self.upload(
            name,
            self.image_bytes(image_format, size, mode=mode, exif=exif),
            content_type,
        )
        return optimize_image_attachment(uploaded_file)

    def output_image(self, result):
        return Image.open(io.BytesIO(result.content))

    def minimal_pdf(self):
        return (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"xref\n0 1\n0000000000 65535 f \n"
            b"trailer\n<< /Root 1 0 R /Size 1 >>\n"
            b"startxref\n45\n%%EOF\n"
        )

    def test_pillow_webp_encoding_and_decoding_are_available(self):
        self.assertTrue(features.check("webp"))
        result = self.process_image("image.jpg", "JPEG", (10, 10))

        with self.output_image(result) as image:
            self.assertEqual(image.format, "WEBP")
            image.load()

    def test_large_landscape_jpeg_resizes_to_longest_side(self):
        result = self.process_image("landscape.jpg", "JPEG", (2400, 1200))

        with self.output_image(result) as image:
            self.assertEqual(image.size, (1920, 960))

    def test_large_portrait_jpeg_resizes_to_longest_side(self):
        result = self.process_image("portrait.jpeg", "JPEG", (1200, 2400))

        with self.output_image(result) as image:
            self.assertEqual(image.size, (960, 1920))

    def test_large_png_resizes_without_crop_or_distortion(self):
        result = self.process_image("large.png", "PNG", (3000, 1500))

        with self.output_image(result) as image:
            self.assertEqual(max(image.size), MAX_IMAGE_DIMENSION)
            self.assertEqual(image.size, (1920, 960))
            self.assertEqual(image.width / image.height, 2)

    def test_small_jpeg_is_not_upscaled(self):
        result = self.process_image("small.jpg", "JPEG", (320, 180))

        with self.output_image(result) as image:
            self.assertEqual(image.size, (320, 180))

    def test_small_png_is_not_upscaled(self):
        result = self.process_image("small.png", "PNG", (180, 320))

        with self.output_image(result) as image:
            self.assertEqual(image.size, (180, 320))

    def test_jpeg_and_png_outputs_are_webp_with_expected_identity(self):
        for name, image_format in (("image.jpg", "JPEG"), ("image.png", "PNG")):
            with self.subTest(name=name):
                result = self.process_image(name, image_format, (20, 20))
                self.assertEqual(result.extension, ".webp")
                self.assertEqual(result.content_type, "image/webp")
                with self.output_image(result) as image:
                    self.assertEqual(image.format, "WEBP")

    def test_transparent_png_remains_transparent(self):
        result = self.process_image(
            "transparent.png", "PNG", (20, 20), mode="RGBA"
        )

        with self.output_image(result) as image:
            converted = image.convert("RGBA")
            self.assertEqual(converted.getpixel((0, 0))[3], 0)

    def test_exif_orientation_is_applied_before_resize(self):
        exif = Image.Exif()
        exif[274] = 6
        result = self.process_image(
            "oriented.jpg",
            "JPEG",
            (2400, 1200),
            exif=exif,
        )

        with self.output_image(result) as image:
            self.assertEqual(image.size, (960, 1920))

    def test_exif_metadata_is_not_retained(self):
        exif = Image.Exif()
        exif[315] = "Test Artist"
        result = self.process_image(
            "metadata.jpg",
            "JPEG",
            (20, 20),
            exif=exif,
        )

        with self.output_image(result) as image:
            self.assertEqual(len(image.getexif()), 0)

    def test_pdf_is_rejected_with_arabic_validation_error(self):
        uploaded_file = self.upload(
            "document.pdf", self.minimal_pdf(), "application/pdf"
        )

        with self.assertRaises(ValidationError) as context:
            optimize_image_attachment(uploaded_file)

        self.assertRegex(str(context.exception), "[\u0600-\u06ff]")

    def test_fake_image_is_rejected(self):
        uploaded_file = self.upload("fake.jpg", b"plain text", "image/jpeg")

        with self.assertRaises(ValidationError):
            optimize_image_attachment(uploaded_file)

    def test_source_stream_is_restored_after_success(self):
        content = self.image_bytes("PNG", (20, 20))
        uploaded_file = self.upload("image.png", content, "image/png")

        result = optimize_image_attachment(uploaded_file)

        self.assertEqual(result.extension, ".webp")
        self.assertEqual(uploaded_file.tell(), 0)
        self.assertEqual(uploaded_file.read(), content)

    def test_source_stream_is_restored_after_failure(self):
        content = b"plain text"
        uploaded_file = self.upload("fake.png", content, "image/png")

        with self.assertRaises(ValidationError):
            optimize_image_attachment(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)
        self.assertEqual(uploaded_file.read(), content)

    def test_processing_policy_constants(self):
        self.assertEqual(MAX_IMAGE_DIMENSION, 1920)
        self.assertEqual(WEBP_QUALITY, 85)
