import signal

from django.core.management.base import BaseCommand

from notifications.push_worker import PushWorker


class Command(BaseCommand):
    help = "Send pending push notifications until SIGTERM or SIGINT."

    def handle(self, *args, **options):
        worker = PushWorker()
        # The current batch finishes before the worker exits with status 0.
        signal.signal(signal.SIGTERM, worker.stop)
        signal.signal(signal.SIGINT, worker.stop)
        worker.run()
