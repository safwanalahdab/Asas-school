from django.core.management.base import BaseCommand

from announcements.services import notify_due_announcements


class Command(BaseCommand):
    help = (
        "Create publish notifications for announcements whose publish date "
        "has arrived. Does nothing before ANNOUNCEMENT_NOTIFY_HOUR."
    )

    def handle(self, *args, **options):
        processed = notify_due_announcements()
        self.stdout.write(f"announcements_notified: {processed}")
