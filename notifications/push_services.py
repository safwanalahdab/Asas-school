from firebase_admin import messaging


def build_notification_message(*, notification, token):
    data = {
        "notification_id": str(notification.id),
        "type": str(notification.notification_type),
        "student_id": str(notification.student_id) if notification.student_id else "",
        "resource_type": str(notification.resource_type or ""),
        "resource_id": str(notification.resource_id) if notification.resource_id else "",
    }
    return messaging.Message(
        notification=messaging.Notification(
            title=notification.title,
            body=notification.body,
        ),
        data=data,
        token=token,
    )


def _unique_token_devices(devices):
    # Active tokens are unique in the database; this only guards against a
    # caller-supplied list sending the same token twice.
    seen, unique = set(), []
    for device in devices:
        if device.fcm_token not in seen:
            seen.add(device.fcm_token)
            unique.append(device)
    return unique
