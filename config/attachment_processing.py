import io
import warnings
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

from config.attachment_validation import read_validated_attachment


MAX_IMAGE_DIMENSION = 1920
MAX_ATTACHMENT_IMAGE_PIXELS = 25_000_000
WEBP_QUALITY = 85

IMAGE_PIXEL_LIMIT_ERROR = (
    "عدد بكسلات الصورة يتجاوز الحد الأقصى المسموح وهو 25 مليون بكسل."
)


@dataclass(frozen=True)
class ProcessedImageAttachment:
    content: bytes
    extension: str = ".webp"
    content_type: str = "image/webp"


def _has_transparency(image):
    return image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )


def optimize_validated_image_content(content):
    """Convert already-validated image bytes to WebP, decoding them once."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > MAX_ATTACHMENT_IMAGE_PIXELS:
                    raise ValidationError(IMAGE_PIXEL_LIMIT_ERROR)

                # In place avoids a full extra copy when there is no rotation.
                ImageOps.exif_transpose(source, in_place=True)
                source.load()

                if max(source.size) > MAX_IMAGE_DIMENSION:
                    source.thumbnail(
                        (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                        Image.Resampling.LANCZOS,
                    )

                with source.convert(
                    "RGBA" if _has_transparency(source) else "RGB"
                ) as output_image:
                    output = io.BytesIO()
                    output_image.save(
                        output,
                        format="WEBP",
                        quality=WEBP_QUALITY,
                        optimize=True,
                    )
        return ProcessedImageAttachment(content=output.getvalue())
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ValidationError("ملف الصورة تالف أو غير صالح للمعالجة.") from exc


def optimize_image_attachment(uploaded_file):
    """Validate and convert an image attachment to a storage-independent WebP."""
    original_position = None
    try:
        if hasattr(uploaded_file, "tell"):
            original_position = uploaded_file.tell()

        extension, content = read_validated_attachment(uploaded_file)
        if extension == ".pdf":
            raise ValidationError("لا يمكن تحسين ملف PDF لأن هذه الدالة مخصصة للصور فقط.")

        return optimize_validated_image_content(content)
    finally:
        if original_position is not None:
            try:
                uploaded_file.seek(original_position)
            except (AttributeError, OSError, ValueError):
                pass
