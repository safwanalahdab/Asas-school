from django.db.models import Count, Sum

from .models import BehaviorNote, StudentPointEntry


def get_mobile_behavior_notes(*, enrollment):
    """Fetch the current enrollment's notes in timeline order."""
    return BehaviorNote.objects.filter(enrollment=enrollment).order_by(
        "-occurred_on",
        "-created_at",
        "-id",
    )


def get_mobile_point_entries(*, enrollment, date_from=None, date_to=None):
    queryset = StudentPointEntry.objects.filter(enrollment=enrollment)
    if date_from is not None:
        queryset = queryset.filter(occurred_on__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(occurred_on__lte=date_to)
    return queryset.order_by("-occurred_on", "-created_at", "-id")


def get_mobile_points_summary(*, queryset):
    summary = queryset.order_by().aggregate(
        total_points=Sum("points"),
        entries_count=Count("id"),
    )
    summary["total_points"] = summary["total_points"] or 0
    return summary
