import io
import re
import warnings
from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

_IMAGE_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
}
_CONTENT_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".jpg": {"image/jpeg", "image/jpg", "application/octet-stream"},
    ".jpeg": {"image/jpeg", "image/jpg", "application/octet-stream"},
    ".png": {"image/png", "application/octet-stream"},
}


def _validate_content_type(uploaded_file, extension):
    content_type = getattr(uploaded_file, "content_type", None)
    if content_type:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized not in _CONTENT_TYPES[extension]:
            raise ValidationError(
                "نوع محتوى الملف المعلن لا يتوافق مع امتداد الملف."
            )


def _validate_image(content, expected_format):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format != expected_format:
                    raise ValidationError(
                        "محتوى ملف الصورة لا يتوافق مع امتداده."
                    )
                image.verify()
    except ValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ValidationError("ملف الصورة تالف أو غير صالح.") from exc


def _validate_pdf(content):
    stripped = content.rstrip()
    has_header = re.match(br"%PDF-[0-9]\.[0-9]", content) is not None
    has_object = re.search(br"(?:^|[\r\n])[ \t]*\d+[ \t]+\d+[ \t]+obj\b", content)
    has_end_object = b"endobj" in content
    has_startxref = re.search(br"startxref\s+\d+", content)
    has_eof = stripped.endswith(b"%%EOF")
    if not all((has_header, has_object, has_end_object, has_startxref, has_eof)):
        raise ValidationError("ملف PDF تالف أو غير صالح.")


def validate_attachment(uploaded_file):
    """Validate an incoming attachment without saving or modifying it."""
    original_position = None
    try:
        if hasattr(uploaded_file, "tell"):
            original_position = uploaded_file.tell()

        name = getattr(uploaded_file, "name", "") or ""
        extension = Path(name).suffix.lower()
        if not extension:
            raise ValidationError("يجب أن يحتوي اسم الملف على امتداد.")
        if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise ValidationError(
                "امتداد الملف غير مسموح. الامتدادات المسموحة: PDF وJPG وJPEG وPNG."
            )

        declared_size = getattr(uploaded_file, "size", None)
        if declared_size is not None and declared_size > MAX_ATTACHMENT_SIZE:
            raise ValidationError("حجم الملف يتجاوز الحد الأقصى المسموح وهو 5 ميغابايت.")

        uploaded_file.seek(0)
        content = uploaded_file.read(MAX_ATTACHMENT_SIZE + 1)
        if len(content) > MAX_ATTACHMENT_SIZE:
            raise ValidationError("حجم الملف يتجاوز الحد الأقصى المسموح وهو 5 ميغابايت.")

        _validate_content_type(uploaded_file, extension)
        if extension in _IMAGE_FORMATS:
            _validate_image(content, _IMAGE_FORMATS[extension])
        else:
            _validate_pdf(content)
    finally:
        if original_position is not None:
            try:
                uploaded_file.seek(original_position)
            except (AttributeError, OSError, ValueError):
                pass

