import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image, ImageOps

from config import attachment_processing, attachment_validation
from config.attachment_preparation import prepare_attachment
from config.attachment_processing import MAX_IMAGE_DIMENSION, WEBP_QUALITY, optimize_image_attachment


def legacy_webp(content):
    """The pre-change conversion (copying exif_transpose), for output equality."""
    with Image.open(io.BytesIO(content)) as source:
        oriented = ImageOps.exif_transpose(source)
        oriented.load()
        if max(oriented.size) > MAX_IMAGE_DIMENSION:
            oriented.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
        output_image = oriented.convert("RGBA" if attachment_processing._has_transparency(oriented) else "RGB")
        output = io.BytesIO()
        output_image.save(output, format="WEBP", quality=WEBP_QUALITY, optimize=True)
    return output.getvalue()


class CountingUpload(SimpleUploadedFile):
    """Records how many bytes are read from the upload in total."""

    bytes_read = 0

    def read(self, *args, **kwargs):
        data = super().read(*args, **kwargs)
        self.bytes_read += len(data)
        return data


class AttachmentHeavyOperationTests(SimpleTestCase):
    def image(self, image_format, size=(60, 30), *, mode="RGB", orientation=None):
        stream = io.BytesIO()
        color = (255, 0, 0, 128) if mode == "RGBA" else "red"
        image = Image.new(mode, size, color=color)
        image.putpixel((0, 0), (0, 0, 255) if mode == "RGB" else (0, 0, 255, 255))
        params = {}
        if orientation:
            exif = Image.Exif()
            exif[0x0112] = orientation
            params["exif"] = exif.tobytes()
        image.save(stream, format=image_format, **params)
        return stream.getvalue()

    def upload(self, name, content, content_type, cls=SimpleUploadedFile):
        return cls(name, content, content_type=content_type)

    def test_output_is_byte_identical_to_previous_processing(self):
        cases = {
            "large jpeg is resized": ("big.jpg", self.image("JPEG", (2400, 1200)), "image/jpeg"),
            "exif rotated jpeg": ("rotated.jpg", self.image("JPEG", (80, 40), orientation=6), "image/jpeg"),
            "transparent png": ("alpha.png", self.image("PNG", mode="RGBA"), "image/png"),
            "small png is not enlarged": ("small.png", self.image("PNG", (20, 10)), "image/png"),
        }
        for case, (name, content, content_type) in cases.items():
            with self.subTest(case=case):
                prepared = prepare_attachment(self.upload(name, content, content_type))
                self.assertEqual(prepared.content, legacy_webp(content))
                with Image.open(io.BytesIO(prepared.content)) as result, Image.open(io.BytesIO(content)) as source:
                    expected = ImageOps.exif_transpose(source).size
                    if max(expected) <= MAX_IMAGE_DIMENSION:
                        self.assertEqual(result.size, expected)
                    else:
                        self.assertEqual(max(result.size), MAX_IMAGE_DIMENSION)

    def test_image_upload_is_read_once_and_opened_twice(self):
        content = self.image("PNG")
        upload = self.upload("image.png", content, "image/png", cls=CountingUpload)

        with patch.object(Image, "open", wraps=Image.open) as image_open:
            prepare_attachment(upload)

        # One bounded read; one open to verify, one to decode (was 3 reads, 3 opens).
        self.assertEqual(upload.bytes_read, len(content))
        self.assertEqual(image_open.call_count, 2)
        self.assertEqual(upload.tell(), 0)

    def test_pdf_upload_is_read_once_and_kept_unchanged(self):
        content = (
            b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Root 1 0 R /Size 1 >>\n"
            b"startxref\n45\n%%EOF\n"
        )
        upload = self.upload("doc.pdf", content, "application/pdf", cls=CountingUpload)

        prepared = prepare_attachment(upload)

        self.assertEqual(prepared.content, content)
        self.assertEqual(upload.bytes_read, len(content))

    def test_reads_are_bounded_even_if_declared_size_is_missing(self):
        content = b"%PDF-1.4\n" + b"x" * attachment_validation.MAX_ATTACHMENT_SIZE
        upload = self.upload("large.pdf", content, "application/pdf", cls=CountingUpload)
        upload.size = None

        with self.assertRaises(ValidationError):
            prepare_attachment(upload)
        self.assertEqual(upload.bytes_read, attachment_validation.MAX_ATTACHMENT_SIZE + 1)

    def test_standalone_optimizer_still_validates(self):
        with self.assertRaises(ValidationError):
            optimize_image_attachment(self.upload("fake.png", b"not an image", "image/png"))
        with self.assertRaises(ValidationError):
            optimize_image_attachment(self.upload("renamed.png", self.image("JPEG"), "image/png"))

    def test_decompression_bomb_is_rejected(self):
        content = self.image("PNG", (40, 40))
        with patch.object(Image, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaises(ValidationError):
                prepare_attachment(self.upload("bomb.png", content, "image/png"))
