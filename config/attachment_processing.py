import io
import warnings
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

from config.attachment_validation import validate_attachment


MAX_IMAGE_DIMENSION = 1920
WEBP_QUALITY = 85


@dataclass(frozen=True)
class ProcessedImageAttachment:
    content: bytes
    extension: str = ".webp"
    content_type: str = "image/webp"


def _has_transparency(image):
    return image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )


def optimize_image_attachment(uploaded_file):
    """Validate and convert an image attachment to a storage-independent WebP."""
    original_position = None
    try:
        if hasattr(uploaded_file, "tell"):
            original_position = uploaded_file.tell()

        validate_attachment(uploaded_file)
        extension = Path(getattr(uploaded_file, "name", "")).suffix.lower()
        if extension == ".pdf":
            raise ValidationError("لا يمكن تحسين ملف PDF لأن هذه الدالة مخصصة للصور فقط.")

        uploaded_file.seek(0)
        source_content = uploaded_file.read()
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source_content)) as source:
                oriented = ImageOps.exif_transpose(source)
                oriented.load()

                if max(oriented.size) > MAX_IMAGE_DIMENSION:
                    oriented.thumbnail(
                        (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                        Image.Resampling.LANCZOS,
                    )

                output_image = oriented.convert(
                    "RGBA" if _has_transparency(oriented) else "RGB"
                )
                output = io.BytesIO()
                output_image.save(
                    output,
                    format="WEBP",
                    quality=WEBP_QUALITY,
                    optimize=True,
                )
        return ProcessedImageAttachment(content=output.getvalue())
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
        raise ValidationError("ملف الصورة تالف أو غير صالح للمعالجة.") from exc
    finally:
        if original_position is not None:
            try:
                uploaded_file.seek(original_position)
            except (AttributeError, OSError, ValueError):
                pass

