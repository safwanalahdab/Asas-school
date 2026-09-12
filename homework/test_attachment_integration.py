import io
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from teaching.models import TeacherAssignment

from .models import Homework


User = get_user_model()


class HomeworkAttachmentIntegrationTests(TestCase):
    list_url = "/api/v1/homework/homeworks/"

    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="homework-attachment-admin",
            password="StrongPass!493",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.teacher = User.objects.create_user(
            username="homework-attachment-teacher",
            password="StrongPass!493",
            role=User.Role.TEACHER,
            must_change_password=False,
        )
        self.guardian = User.objects.create_user(
            username="homework-attachment-guardian",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="Attachment Grade",
        )
        section = Section.objects.create(
            academic_year=year,
            grade_level=grade,
            name="A",
        )
        subject = Subject.objects.create(name="Attachment Subject")
        grade_subject = GradeSubject.objects.create(
            academic_year=year,
            grade_level=grade,
            subject=subject,
        )
        self.assignment = TeacherAssignment.objects.create(
            teacher=self.teacher,
            grade_subject=grade_subject,
            section=section,
            start_date=date(2026, 9, 1),
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def image_upload(self, name, image_format, size=(40, 20), transparent=False):
        stream = io.BytesIO()
        mode = "RGBA" if transparent else "RGB"
        color = (255, 0, 0, 0) if transparent else "red"
        Image.new(mode, size, color=color).save(stream, format=image_format)
        content_type = "image/jpeg" if image_format == "JPEG" else "image/png"
        return SimpleUploadedFile(name, stream.getvalue(), content_type=content_type)

    def minimal_pdf(self):
        return (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"xref\n0 1\n0000000000 65535 f \n"
            b"trailer\n<< /Root 1 0 R /Size 1 >>\n"
            b"startxref\n45\n%%EOF\n"
        )

    def homework_data(self, attachment=None, **overrides):
        data = {
            "teacher_assignment": str(self.assignment.id),
            "title": "Attachment homework",
            "description": "Description",
            "homework_date": "2026-09-03",
            "due_date": "2026-09-04",
        }
        if attachment is not None:
            data["attachment"] = attachment
        data.update(overrides)
        return data

    def create_via_api(self, attachment=None, **overrides):
        return self.client.post(
            self.list_url,
            self.homework_data(attachment, **overrides),
            format="multipart",
        )

    def stored_homework(self, response):
        return Homework.objects.get(pk=response.data["data"]["id"])

    def assert_uuid_filename(self, stored_name, extension):
        path = Path(stored_name)
        self.assertEqual(path.parent.as_posix(), "homework/attachments")
        self.assertEqual(path.suffix, extension)
        self.assertEqual(UUID(path.stem).version, 4)

    def test_jpeg_upload_is_saved_as_resized_uuid_webp(self):
        response = self.create_via_api(
            self.image_upload("original-family-photo.jpg", "JPEG", (2400, 1200))
        )

        self.assertEqual(response.status_code, 201)
        homework = self.stored_homework(response)
        self.assert_uuid_filename(homework.attachment.name, ".webp")
        self.assertNotIn("original-family-photo", homework.attachment.name)
        self.assertTrue(response.data["data"]["attachment"].endswith(".webp"))
        with homework.attachment.open("rb") as stored_file:
            with Image.open(stored_file) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (1920, 960))

    def test_png_upload_is_saved_as_webp(self):
        response = self.create_via_api(
            self.image_upload("diagram.png", "PNG")
        )

        self.assertEqual(response.status_code, 201)
        homework = self.stored_homework(response)
        self.assert_uuid_filename(homework.attachment.name, ".webp")
        with homework.attachment.open("rb") as stored_file:
            with Image.open(stored_file) as image:
                self.assertEqual(image.format, "WEBP")

    def test_transparent_png_retains_transparency(self):
        response = self.create_via_api(
            self.image_upload("transparent.png", "PNG", transparent=True)
        )

        self.assertEqual(response.status_code, 201)
        homework = self.stored_homework(response)
        with homework.attachment.open("rb") as stored_file:
            with Image.open(stored_file) as image:
                self.assertEqual(image.convert("RGBA").getpixel((0, 0))[3], 0)

    def test_pdf_upload_keeps_bytes_and_uses_uuid_filename(self):
        content = self.minimal_pdf()
        response = self.create_via_api(
            SimpleUploadedFile(
                "student-homework.pdf",
                content,
                content_type="application/pdf",
            )
        )

        self.assertEqual(response.status_code, 201)
        homework = self.stored_homework(response)
        self.assert_uuid_filename(homework.attachment.name, ".pdf")
        self.assertNotIn("student-homework", homework.attachment.name)
        with homework.attachment.open("rb") as stored_file:
            self.assertEqual(stored_file.read(), content)

    def test_invalid_attachments_are_field_errors_with_arabic_messages(self):
        invalid_uploads = (
            SimpleUploadedFile("file.txt", b"text", content_type="text/plain"),
            SimpleUploadedFile("fake.jpg", b"text", content_type="image/jpeg"),
            SimpleUploadedFile(
                "fake.pdf", b"plain text", content_type="application/pdf"
            ),
            SimpleUploadedFile(
                "large.pdf",
                b"%PDF-1.4\n" + b"x" * (5 * 1024 * 1024),
                content_type="application/pdf",
            ),
        )
        for uploaded_file in invalid_uploads:
            with self.subTest(name=uploaded_file.name):
                response = self.create_via_api(uploaded_file)
                self.assertEqual(response.status_code, 400)
                self.assertIn("attachment", response.data["errors"])
                self.assertRegex(
                    str(response.data["errors"]["attachment"]),
                    "[\u0600-\u06ff]",
                )

    def test_patch_without_attachment_preserves_name_and_content(self):
        created = self.create_via_api(
            self.image_upload("original.png", "PNG")
        )
        homework = self.stored_homework(created)
        original_name = homework.attachment.name
        with homework.attachment.open("rb") as stored_file:
            original_content = stored_file.read()

        response = self.client.patch(
            f"{self.list_url}{homework.id}/",
            {"title": "Updated title"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        homework.refresh_from_db()
        self.assertEqual(homework.attachment.name, original_name)
        with homework.attachment.open("rb") as stored_file:
            self.assertEqual(stored_file.read(), original_content)

    def test_patch_with_explicit_null_clears_attachment(self):
        created = self.create_via_api(
            self.image_upload("original.png", "PNG")
        )
        homework = self.stored_homework(created)

        response = self.client.patch(
            f"{self.list_url}{homework.id}/",
            {"attachment": None},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        homework.refresh_from_db()
        self.assertFalse(homework.attachment)

    def test_patch_with_attachment_replaces_reference_with_new_webp(self):
        created = self.create_via_api(
            SimpleUploadedFile(
                "original.pdf",
                self.minimal_pdf(),
                content_type="application/pdf",
            )
        )
        homework = self.stored_homework(created)
        original_name = homework.attachment.name

        response = self.client.patch(
            f"{self.list_url}{homework.id}/",
            {"attachment": self.image_upload("replacement.jpg", "JPEG")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        homework.refresh_from_db()
        self.assertNotEqual(homework.attachment.name, original_name)
        self.assert_uuid_filename(homework.attachment.name, ".webp")

    def test_homework_without_attachment_still_creates(self):
        response = self.create_via_api()

        self.assertEqual(response.status_code, 201)
        self.assertFalse(self.stored_homework(response).attachment)

    def test_guardian_cannot_write_homework(self):
        self.client.force_authenticate(self.guardian, token={"client": "web"})

        response = self.create_via_api(
            self.image_upload("image.png", "PNG")
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Homework.objects.count(), 0)
