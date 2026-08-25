from tempfile import TemporaryDirectory

from dotenv import load_dotenv
from flask import Flask, render_template, request
from google import genai
from PIL import UnidentifiedImageError

from services.image_processing import prepare_uploaded_image
from services.parcel_reader import read_parcel

from services.resident_matcher import (normalize_phone, search_csv)


load_dotenv()

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp",
    "heic",
    "heif",
}

MAX_IMAGES = 20


def allowed_file(filename):
    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_EXTENSIONS


def create_display_room(parcel):
    """
    Create one readable room value from Gemini's structured fields.
    """
    if parcel.raw_room_text:
        return parcel.raw_room_text

    room = parcel.room_number

    if room and parcel.room_letter:
        room = f"{room}{parcel.room_letter}"

    if room and parcel.building_number:
        room = f"{parcel.building_number}-{room}"

    return room


@app.route("/", methods=["GET", "POST"])
def home():
    error = None
    parcel_results = []

    if request.method == "POST":
        images = [
            image
            for image in request.files.getlist("parcel_images")
            if image and image.filename
        ]

        if not images:
            error = "Please select at least one parcel image."

        elif len(images) > MAX_IMAGES:
            error = f"You can upload a maximum of {MAX_IMAGES} images."

        elif any(not allowed_file(image.filename) for image in images):
            error = "One or more files use an unsupported format."

        else:
            try:
                gemini_client = genai.Client()

                with TemporaryDirectory() as temporary_directory:
                    for image in images:
                        try:
                            jpeg_path = prepare_uploaded_image(
                                uploaded_file=image,
                                temporary_directory=temporary_directory,
                            )

                            parcel = read_parcel(
                                image_path=jpeg_path,
                                client=gemini_client,
                            )

                            normalized_phone = normalize_phone(
                                parcel.phone_number
                            )

                            if parcel.recipient_full_name:
                                match_result = search_csv(
                                    search_name=parcel.recipient_full_name,
                                    building_number=parcel.building_number,
                                    room_number=parcel.room_number,
                                    room_letter=parcel.room_letter,
                                    phone_number=normalized_phone,
                                )
                            else:
                                match_result = {
                                    "status": "not_found",
                                    "reason": "No recipient name was detected.",
                                    "resident": None,
                                    "scores": {},
                                    "evidence": [],
                                    "candidates": [],
                                }

                            parcel_results.append({
                                "filename": image.filename,
                                "success": True,

                                "parcel": {
                                    "recipient_name": (
                                        parcel.recipient_full_name
                                    ),
                                    "phone_number": normalized_phone,
                                    "room": create_display_room(parcel),
                                    "tracking_number": (
                                        parcel.tracking_number
                                    ),
                                    "ocr_confidence": parcel.confidence,
                                },

                                "match": match_result,
                            })

                        except (
                            UnidentifiedImageError,
                            OSError,
                            ValueError,
                        ) as image_error:
                            parcel_results.append({
                                "filename": image.filename,
                                "success": False,
                                "error": (
                                    "The image could not be read: "
                                    f"{image_error}"
                                ),
                            })

                        except Exception as gemini_error:
                            parcel_results.append({
                                "filename": image.filename,
                                "success": False,
                                "error": (
                                    "Gemini could not process this image: "
                                    f"{gemini_error}"
                                ),
                            })

                # Temporary images are deleted here.

            except Exception as connection_error:
                error = (
                    "The Gemini service could not be started: "
                    f"{connection_error}"
                )

    return render_template(
        "index.html",
        error=error,
        parcel_results=parcel_results,
    )


@app.errorhandler(413)
def upload_too_large(_error):
    return render_template(
        "index.html",
        error="The selected images are too large. The maximum total is 50 MB.",
        parcel_results=[],
    ), 413


if __name__ == "__main__":
    app.run()