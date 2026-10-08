import logging
from contextlib import contextmanager

from django.db import transaction


logger = logging.getLogger(__name__)


def _storage_for(model, field_name):
    return model._meta.get_field(field_name).storage


def _delete_quietly(storage, name, model_label, reason):
    """Remove a stored file, logging instead of raising on failure.

    Only the model and the error type are logged: never the file name, which
    may predate UUID naming and carry personal data, nor its content.
    """
    try:
        if storage.exists(name):
            storage.delete(name)
    except Exception as error:
        logger.warning(
            "Could not delete %s attachment model=%s error=%s",
            reason,
            model_label,
            type(error).__name__,
        )


@contextmanager
def discard_new_attachment_on_error(model, upload, field_name="attachment"):
    """Delete a newly stored attachment if the surrounding write fails.

    FileField writes the file to storage during ``save()``, before the
    database commits, so a failed write would leave it orphaned. Wrap the whole
    atomic block, commit included. Only use this for uploads with freshly
    generated unique names (see prepare_attachment): the path it removes is
    derived from that name, so it can never be an existing, referenced file.
    """
    try:
        yield
    except BaseException:
        name = getattr(upload, "name", None)
        if name:
            field = model._meta.get_field(field_name)
            stored_name = field.generate_filename(None, name)
            _delete_quietly(field.storage, stored_name, model._meta.label, "orphaned")
        raise


def delete_attachment_on_commit(model, name, field_name="attachment"):
    """Delete a no longer referenced stored file once the transaction commits.

    Call inside the atomic block that drops the reference. On rollback Django
    discards the callback, so the file stays with the row that still uses it.
    A storage failure after the commit is logged and never fails the request.
    """
    if not name:
        return
    storage = _storage_for(model, field_name)
    model_label = model._meta.label
    transaction.on_commit(
        lambda: _delete_quietly(storage, name, model_label, "previous"),
    )


def delete_replaced_attachment_on_commit(
    instance, previous_name, field_name="attachment",
):
    """Delete the previous file after commit if the saved instance dropped it.

    Covers both a replacement and an explicit ``null``; an unchanged name
    (including an update that did not touch the field) deletes nothing.
    """
    current_name = getattr(instance, field_name).name or ""
    if previous_name and previous_name != current_name:
        delete_attachment_on_commit(type(instance), previous_name, field_name)
