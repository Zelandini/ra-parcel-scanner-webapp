from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


register_heif_opener()

JPEG_QUALITY = 90


def convert_to_rgb(image):
    """
    Correct the image rotation and convert it into an RGB image
    suitable for JPEG.
    """
    image = ImageOps.exif_transpose(image)

    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        transparent_image = image.convert("RGBA")

        background = Image.new(
            "RGB",
            transparent_image.size,
            "white",
        )

        background.paste(
            transparent_image,
            mask=transparent_image.getchannel("A"),
        )

        return background

    return image.convert("RGB")


def prepare_uploaded_image(
    uploaded_file: FileStorage,
    temporary_directory: str,
) -> Path:
    """
    Validate an uploaded image and convert it to a temporary JPEG.

    The caller is responsible for deleting the temporary directory.
    """
    original_filename = secure_filename(uploaded_file.filename)

    if not original_filename:
        original_filename = "parcel-image"

    unique_name = uuid4().hex
    original_extension = Path(original_filename).suffix.lower()

    original_path = Path(temporary_directory) / (
        f"{unique_name}{original_extension}"
    )

    jpeg_path = Path(temporary_directory) / (
        f"{unique_name}.jpg"
    )

    uploaded_file.save(original_path)

    with Image.open(original_path) as image:
        if getattr(image, "is_animated", False):
            image.seek(0)

        rgb_image = convert_to_rgb(image)

        rgb_image.save(
            jpeg_path,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
        )

    return jpeg_path