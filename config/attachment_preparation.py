from dataclasses import dataclass
from uuid import uuid4

from config.attachment_processing import optimize_validated_image_content
from config.attachment_validation import read_validated_attachment


@dataclass(frozen=True)
class PreparedAttachment:
    content: bytes
    filename: str
    content_type: str


def prepare_attachment(uploaded_file):
    """Prepare a validated attachment without saving it to any storage backend."""
    original_position = None
    try:
        if hasattr(uploaded_file, "tell"):
            original_position = uploaded_file.tell()

        # One bounded read and one validation pass serve both branches.
        extension, content = read_validated_attachment(uploaded_file)

        if extension == ".pdf":
            return PreparedAttachment(
                content=content,
                filename=f"{uuid4()}.pdf",
                content_type="application/pdf",
            )

        processed = optimize_validated_image_content(content)
        return PreparedAttachment(
            content=processed.content,
            filename=f"{uuid4()}{processed.extension}",
            content_type=processed.content_type,
        )
    finally:
        if original_position is not None:
            try:
                uploaded_file.seek(original_position)
            except (AttributeError, OSError, ValueError):
                pass

