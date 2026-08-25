from flask import Flask, render_template, request

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


def allowed_file(filename):
    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_EXTENSIONS


@app.route("/", methods=["GET", "POST"])
def home():
    error = None
    uploaded_count = None

    if request.method == "POST":
        images = request.files.getlist("parcel_images")

        images = [
            image
            for image in images
            if image and image.filename
        ]

        if not images:
            error = "Please select at least one parcel image."

        elif len(images) > 20:
            error = "You can upload a maximum of 20 images."

        elif any(not allowed_file(image.filename) for image in images):
            error = "One or more files use an unsupported format."

        else:
            uploaded_count = len(images)

            # We are only validating the images at this stage.
            # Nothing is permanently stored yet.

    return render_template(
        "index.html",
        error=error,
        uploaded_count=uploaded_count,
    )


@app.errorhandler(413)
def upload_too_large(error):
    return render_template(
        "index.html",
        error="The selected images are too large. The maximum total is 50 MB.",
        uploaded_count=None,
    ), 413


if __name__ == "__main__":
    app.run()