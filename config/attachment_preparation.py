from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from config.attachment_processing import optimize_image_attachment
from config.attachment_validation import validate_attachment


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

        validate_attachment(uploaded_file)
        extension = Path(getattr(uploaded_file, "name", "")).suffix.lower()

        if extension == ".pdf":
            uploaded_file.seek(0)
            return PreparedAttachment(
                content=uploaded_file.read(),
                filename=f"{uuid4()}.pdf",
                content_type="application/pdf",
            )

        processed = optimize_image_attachment(uploaded_file)
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

