from .models import BehaviorNote


def get_mobile_behavior_notes(*, enrollment):
    """Fetch the current enrollment's notes in timeline order."""
    return BehaviorNote.objects.filter(enrollment=enrollment).order_by(
        "-occurred_on",
        "-created_at",
        "-id",
    )
