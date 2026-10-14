from django.core.management.base import BaseCommand, CommandError

from notifications.push_worker import get_queue_status


class Command(BaseCommand):
    help = (
        "Print push outbox counts by status. Exits non-zero when a due "
        "pending push has waited longer than --max-age-seconds."
    )

    def add_arguments(self, parser):
        parser.add_argument("--max-age-seconds", type=int, default=300)

    def handle(self, *args, **options):
        status = get_queue_status()
        for push_status, total in status.counts.items():
            self.stdout.write(f"{push_status}: {total}")
        self.stdout.write(
            f"oldest_pending_age_seconds: {_seconds(status.oldest_pending_age_seconds)}"
        )
        self.stdout.write(
            f"oldest_due_overdue_seconds: {_seconds(status.oldest_due_overdue_seconds)}"
        )

        overdue = status.oldest_due_overdue_seconds
        if overdue is not None and overdue > options["max_age_seconds"]:
            raise CommandError(
                f"A due push has waited {int(overdue)}s "
                f"(limit {options['max_age_seconds']}s); is run_push_worker running?"
            )


def _seconds(value):
    return "-" if value is None else int(value)
