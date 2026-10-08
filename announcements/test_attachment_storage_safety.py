from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from config.attachment_lifecycle_testing import AttachmentLifecycleTestsMixin

from .models import Announcement


User = get_user_model()


class AnnouncementAttachmentStorageSafetyTests(AttachmentLifecycleTestsMixin, TestCase):
    """Announcements follow the same attachment preparation and file lifecycle as homework."""

    model = Announcement
    list_url = "/api/v1/announcements/"
    upload_dir = "announcements/attachments"
    notify_path = "announcements.views.notify_announcement_published"

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="announcement-storage-admin", password="StrongPass!493",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def create_payload(self):
        return {
            "scope": Announcement.Scope.ALL, "title": "Notice",
            "content": "Content", "publish_date": str(timezone.localdate()),
        }

    def create_existing(self, attachment):
        return Announcement.objects.create(
            scope=Announcement.Scope.ALL, title="Legacy notice", content="Content",
            publish_date=timezone.localdate(), attachment=attachment, created_by=self.admin,
        )
