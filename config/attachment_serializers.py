from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.base import ContentFile
from rest_framework import serializers

from config.attachment_preparation import prepare_attachment


class PreparedAttachmentSerializerMixin:
    """Validate and normalize a new ``attachment`` upload before it is stored.

    Only runs for uploads present in the request, so an existing stored file
    is never re-processed when another field is edited.
    """

    def validate_attachment(self, uploaded_file):
        if uploaded_file is None:
            return None

        try:
            prepared = prepare_attachment(uploaded_file)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

        attachment = ContentFile(prepared.content, name=prepared.filename)
        attachment.content_type = prepared.content_type
        return attachment
