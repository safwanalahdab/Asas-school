"""Test helpers for code that sends through firebase_admin.messaging.send_each."""

from firebase_admin import messaging


def fake_send_each(errors_by_token=None):
    """Build a send_each stand-in returning real BatchResponse objects.

    Messages whose token is in ``errors_by_token`` fail with that exception;
    every other message succeeds.
    """
    errors_by_token = errors_by_token or {}

    def send_each(messages, dry_run=False, app=None):
        return messaging.BatchResponse([
            messaging.SendResponse(None, errors_by_token[message.token])
            if message.token in errors_by_token
            else messaging.SendResponse({"name": f"projects/test/messages/{index}"}, None)
            for index, message in enumerate(messages)
        ])

    return send_each


def sent_tokens(send_each_mock):
    """Every token passed to a patched send_each, in call order."""
    return [
        message.token
        for call in send_each_mock.call_args_list
        for message in call.args[0]
    ]
