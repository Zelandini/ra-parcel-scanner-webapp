import os
import re
import secrets
from functools import wraps
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFProtect
from google import genai
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from PIL import UnidentifiedImageError

from services.alias_repository import (
    AliasAlreadyExistsError,
    AliasNotFoundError,
    InvalidAliasError,
    deactivate_alias,
    find_active_alias_resident_ids,
    get_active_aliases_for_resident,
    get_alias,
    list_active_aliases,
    replace_alias,
    save_alias,
)
from services.batch_repository import (
    BatchNotFoundError,
    cleanup_expired_batches,
    complete_batch,
    create_batch,
    create_processing_item,
    delete_batch,
    finish_batch_upload,
    get_batch,
    get_batch_item,
    get_batch_items,
    list_batches,
    refresh_batch_summary,
    save_item_failure,
    save_item_result,
    update_batch_item,
)
from services.image_processing import prepare_uploaded_image
from services.parcel_reader import read_parcel
from services.resident_matcher import (
    get_resident_by_student_id,
    normalize_name,
    normalize_phone,
    search_residents,
    search_csv,
)


load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("APP_ENV", "development").lower()
    == "production"
)

csrf = CSRFProtect(app)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

APPROVED_RA_EMAILS = {
    email.strip().lower()
    for email in os.getenv("APPROVED_RA_EMAILS", "").split(",")
    if email.strip()
}

if not app.config["SECRET_KEY"]:
    raise RuntimeError("FLASK_SECRET_KEY is not configured.")

if not GOOGLE_CLIENT_ID:
    raise RuntimeError("GOOGLE_CLIENT_ID is not configured.")

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


def login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if "google_sub" not in session:
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapped_view


def get_owned_batch_or_404(batch_id):
    try:
        return get_batch(batch_id, session["google_sub"])
    except BatchNotFoundError:
        abort(404)


def create_display_room(parcel):
    if parcel.raw_room_text:
        return parcel.raw_room_text

    room = parcel.room_number

    if room and parcel.room_letter:
        room = f"{room}{parcel.room_letter}"

    if room and parcel.building_number:
        room = f"{parcel.building_number}-{room}"

    return room


def find_saved_alias_match(detected_name):
    try:
        resident_ids = find_active_alias_resident_ids(detected_name)
    except Exception:
        app.logger.exception("Saved aliases could not be searched.")
        return None

    if len(resident_ids) != 1:
        return None

    resident = get_resident_by_student_id(resident_ids[0])

    if not resident:
        app.logger.warning(
            "Saved alias points to missing resident ID %s.",
            resident_ids[0],
        )
        return None

    return {
        "status": "confirmed",
        "detected_name": detected_name,
        "reason": "Matched using a saved resident alias.",
        "resident": resident,
        "surname_match_type": "saved_alias",
        "scores": {"alias": 100.0, "total": 100.0},
        "evidence": ["saved alias matched exactly"],
        "candidates": [
            {
                "resident": resident,
                "scores": {"alias": 100.0, "total": 100.0},
                "evidence": ["saved alias matched exactly"],
            }
        ],
    }


def match_resident(
    detected_name,
    building_number=None,
    room_number=None,
    room_letter=None,
    phone_number=None,
):
    if not detected_name:
        return {
            "status": "not_found",
            "reason": "No recipient name was detected.",
            "resident": None,
            "scores": {},
            "evidence": [],
            "candidates": [],
        }

    return (
        find_saved_alias_match(detected_name)
        or search_csv(
            search_name=detected_name,
            building_number=building_number,
            room_number=room_number,
            room_letter=room_letter,
            phone_number=phone_number,
        )
    )


def _safe_resident(resident):
    if not resident:
        return None

    return {
        "student_id": str(resident.get("student_id", "")),
        "full_name": str(resident.get("full_name", "")),
        "legal_full_name": str(
            resident.get("legal_full_name", "")
        ),
        "room": str(resident.get("room", "")),
        "building": str(resident.get("building", "")),
    }


def _safe_match(match_result):
    candidates = []

    for candidate in match_result.get("candidates", []):
        candidates.append({
            "resident": _safe_resident(candidate.get("resident")),
            "scores": candidate.get("scores", {}),
            "evidence": candidate.get("evidence", []),
        })

    return {
        "status": match_result.get("status", "not_found"),
        "reason": match_result.get("reason", ""),
        "resident": _safe_resident(match_result.get("resident")),
        "scores": match_result.get("scores", {}),
        "evidence": match_result.get("evidence", []),
        "candidates": candidates,
    }


def can_save_alias(detected_name, resident):
    if not detected_name or not resident:
        return False

    normalized_detected = normalize_name(detected_name)
    registered_names = {
        normalize_name(resident.get("full_name")),
        normalize_name(resident.get("legal_full_name")),
    }

    return (
        bool(normalized_detected)
        and normalized_detected not in registered_names
    )


def _comparison_row(
    label,
    parcel_value,
    resident_value,
    status,
    result_label,
):
    return {
        "label": label,
        "parcel_value": str(parcel_value or ""),
        "resident_value": str(resident_value or ""),
        "status": status,
        "result_label": result_label,
    }


def _compare_name(detected_name, resident, aliases):
    registered_names = {
        normalize_name(resident.get("full_name")),
        normalize_name(resident.get("legal_full_name")),
    }
    registered_names.discard("")
    normalized_detected = normalize_name(detected_name)

    if not normalized_detected:
        status = "missing"
        label = "Not detected"
    elif normalized_detected in registered_names:
        status = "supporting"
        label = "Exact registered name"
    elif normalized_detected in {
        normalize_name(alias)
        for alias in aliases
    }:
        status = "supporting"
        label = "Exact saved alias"
    else:
        status = "review"
        label = "Not exact — review"

    return _comparison_row(
        "Name",
        detected_name,
        resident.get("full_name"),
        status,
        label,
    )


def _compare_phone(detected_phone, resident_phone):
    detected = normalize_phone(detected_phone)
    registered = normalize_phone(resident_phone)

    if not detected:
        status = "missing"
        label = "Not detected"
    elif not registered:
        status = "missing"
        label = "Not in resident record"
    elif detected == registered or (
        len(detected) >= 8
        and len(registered) >= 8
        and detected[-8:] == registered[-8:]
    ):
        status = "supporting"
        label = "Same phone number"
    else:
        status = "conflict"
        label = "Different phone number"

    return _comparison_row(
        "Phone",
        detected_phone,
        resident_phone,
        status,
        label,
    )


def _normalize_room_for_comparison(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _compare_room(detected_room, resident_room):
    detected = _normalize_room_for_comparison(detected_room)
    registered = _normalize_room_for_comparison(resident_room)

    if not detected:
        status = "missing"
        label = "Not detected"
    elif not registered:
        status = "missing"
        label = "Not in resident record"
    elif detected == registered:
        status = "supporting"
        label = "Exact room"
    elif (
        min(len(detected), len(registered)) >= 3
        and (
            detected.endswith(registered)
            or registered.endswith(detected)
        )
    ):
        status = "review"
        label = "Partial room — review"
    else:
        status = "conflict"
        label = "Different room"

    return _comparison_row(
        "Room",
        detected_room,
        resident_room,
        status,
        label,
    )


def build_match_comparison(item, resident, aliases):
    detected = item.get("detected", {})
    rows = [
        _compare_name(
            detected.get("name", ""),
            resident,
            aliases,
        ),
        _compare_phone(
            detected.get("phone", ""),
            resident.get("phone_number", ""),
        ),
        _compare_room(
            detected.get("room_display", ""),
            resident.get("room", ""),
        ),
    ]

    return {
        "rows": rows,
        "supporting_count": sum(
            row["status"] == "supporting"
            for row in rows
        ),
        "review_count": sum(
            row["status"] == "review"
            for row in rows
        ),
        "conflict_count": sum(
            row["status"] == "conflict"
            for row in rows
        ),
        "missing_count": sum(
            row["status"] == "missing"
            for row in rows
        ),
    }


def process_uploaded_image(uploaded_file):
    gemini_client = genai.Client()

    with TemporaryDirectory() as temporary_directory:
        jpeg_path = prepare_uploaded_image(
            uploaded_file=uploaded_file,
            temporary_directory=temporary_directory,
        )

        parcel = read_parcel(
            image_path=jpeg_path,
            client=gemini_client,
        )

    normalized_phone = normalize_phone(parcel.phone_number)
    match_result = match_resident(
        detected_name=parcel.recipient_full_name,
        building_number=parcel.building_number,
        room_number=parcel.room_number,
        room_letter=parcel.room_letter,
        phone_number=normalized_phone,
    )

    safe_match = _safe_match(match_result)

    return {
        "detected": {
            "name": parcel.recipient_full_name or "",
            "phone": normalized_phone,
            "building_number": parcel.building_number or "",
            "room_number": parcel.room_number or "",
            "room_letter": parcel.room_letter or "",
            "room_display": create_display_room(parcel) or "",
            "ocr_confidence": parcel.confidence,
        },
        "match": safe_match,
        "can_save_alias": can_save_alias(
            parcel.recipient_full_name,
            safe_match.get("resident"),
        ),
    }


def prepare_items_for_review(batch_id, items):
    summary_changed = False

    for item in items:
        match = item.get("match", {})

        if (
            item.get("processing_status") == "ready"
            and item.get("review_status") == "pending"
            and match.get("status") == "confirmed"
            and match.get("resident")
        ):
            update_batch_item(
                batch_id,
                item["id"],
                {
                    "review_status": "confirmed",
                    "confirmation_source": "automatic",
                },
                refresh=False,
            )
            item["review_status"] = "confirmed"
            item["confirmation_source"] = "automatic"
            summary_changed = True

        resident = item.get("match", {}).get("resident")
        resident_id = (
            resident.get("student_id")
            if resident
            else None
        )

        if not resident_id:
            item["aliases"] = []
            item["comparison"] = None
            continue

        try:
            item["aliases"] = get_active_aliases_for_resident(
                resident_id
            )
            full_resident = get_resident_by_student_id(resident_id)
            item["comparison"] = build_match_comparison(
                item,
                full_resident or resident,
                item["aliases"],
            )
        except Exception:
            app.logger.exception(
                "Review evidence could not be loaded for a batch item."
            )
            item["aliases"] = []
            item["comparison"] = build_match_comparison(
                item,
                resident,
                [],
            )

    if summary_changed:
        refresh_batch_summary(batch_id)

    return items


@app.template_filter("batch_time")
def batch_time(value):
    if not value:
        return "Unknown time"
    return value.astimezone(
        ZoneInfo("Pacific/Auckland")
    ).strftime("%d %b, %I:%M %p")


@app.route("/login")
def login():
    if "google_sub" in session:
        return redirect(url_for("home"))

    login_csrf_token = secrets.token_urlsafe(32)
    session["login_csrf_token"] = login_csrf_token

    return render_template(
        "login.html",
        google_client_id=GOOGLE_CLIENT_ID,
        login_csrf_token=login_csrf_token,
    )


@app.route("/auth/google", methods=["POST"])
@csrf.exempt
def google_login():
    submitted_data = request.get_json(silent=True) or {}
    submitted_csrf_token = submitted_data.get("csrf_token", "")
    saved_csrf_token = session.pop("login_csrf_token", "")

    if (
        not submitted_csrf_token
        or not saved_csrf_token
        or not secrets.compare_digest(
            submitted_csrf_token,
            saved_csrf_token,
        )
    ):
        return jsonify({
            "error": "The login request could not be verified."
        }), 400

    credential = submitted_data.get("credential")

    if not credential:
        return jsonify({
            "error": "Google did not provide a login credential."
        }), 400

    try:
        google_user = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except ValueError:
        return jsonify({
            "error": "Google could not verify this login."
        }), 401

    email = str(google_user.get("email", "")).strip().lower()

    if not email or not google_user.get("email_verified"):
        return jsonify({
            "error": "The Google email is not verified."
        }), 403

    if email not in APPROVED_RA_EMAILS:
        return jsonify({
            "error": "This Google account is not approved."
        }), 403

    session.clear()
    session["google_sub"] = google_user["sub"]
    session["email"] = email
    session["name"] = google_user.get("name") or email
    session["picture"] = google_user.get("picture")

    return jsonify({"redirect": url_for("home")})


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    try:
        cleanup_expired_batches(session["google_sub"])
        active_batches = list_batches(session["google_sub"])
    except Exception:
        app.logger.exception("Active batches could not be loaded.")
        active_batches = []
        flash(
            "Active batches could not be loaded right now.",
            "error",
        )

    return render_template(
        "index.html",
        active_batches=active_batches[:3],
        max_images=MAX_IMAGES,
    )


@app.route("/batches")
@login_required
def batches_dashboard():
    try:
        cleanup_expired_batches(session["google_sub"])
        batches = list_batches(session["google_sub"])
    except Exception:
        app.logger.exception("The batch dashboard could not load.")
        batches = []
        flash(
            "The batch dashboard could not be loaded.",
            "error",
        )

    return render_template(
        "dashboard.html",
        batches=batches,
    )


@app.route("/aliases")
@login_required
def aliases_manager():
    try:
        aliases = list_active_aliases()

        for alias in aliases:
            alias["resident"] = get_resident_by_student_id(
                alias["resident_id"]
            )

    except Exception:
        app.logger.exception("The alias manager could not load.")
        aliases = []
        flash("Resident aliases could not be loaded.", "error")

    return render_template(
        "aliases.html",
        aliases=aliases,
    )


@app.route("/aliases/add", methods=["POST"])
@login_required
def add_managed_alias():
    resident_id = request.form.get("resident_id", "").strip()
    alias = request.form.get("alias", "").strip()
    resident = get_resident_by_student_id(resident_id)

    if not resident:
        flash("Choose a valid resident first.", "error")
        return redirect(url_for("aliases_manager"))

    try:
        save_alias(
            alias=alias,
            resident=resident,
            created_by_sub=session["google_sub"],
            created_by_email=session["email"],
        )
    except AliasAlreadyExistsError:
        flash("That alias is already active for this resident.", "warning")
    except InvalidAliasError as error:
        flash(str(error), "error")
    except Exception:
        app.logger.exception("A managed alias could not be added.")
        flash("The alias could not be added.", "error")
    else:
        flash("The resident alias was added.", "success")

    return redirect(url_for("aliases_manager"))


@app.route("/aliases/<alias_id>/edit", methods=["POST"])
@login_required
def edit_managed_alias(alias_id):
    new_alias = request.form.get("new_alias", "").strip()

    try:
        existing = get_alias(alias_id)
        resident = get_resident_by_student_id(
            existing.get("resident_id")
        )

        if not resident:
            raise InvalidAliasError(
                "The alias resident could not be found."
            )

        replace_alias(
            alias_id=alias_id,
            new_alias=new_alias,
            resident=resident,
            changed_by_sub=session["google_sub"],
            changed_by_email=session["email"],
        )
    except AliasAlreadyExistsError:
        flash("That replacement alias already exists.", "warning")
    except (AliasNotFoundError, InvalidAliasError) as error:
        flash(str(error), "error")
    except Exception:
        app.logger.exception("A managed alias could not be edited.")
        flash("The alias could not be edited.", "error")
    else:
        flash("The resident alias was updated.", "success")

    return redirect(url_for("aliases_manager"))


@app.route("/aliases/<alias_id>/deactivate", methods=["POST"])
@login_required
def deactivate_managed_alias(alias_id):
    try:
        deactivate_alias(
            alias_id=alias_id,
            changed_by_sub=session["google_sub"],
            changed_by_email=session["email"],
        )
    except AliasNotFoundError as error:
        flash(str(error), "warning")
    except Exception:
        app.logger.exception("A managed alias could not be deactivated.")
        flash("The alias could not be removed.", "error")
    else:
        flash(
            "The alias was removed from future matching.",
            "success",
        )

    return redirect(url_for("aliases_manager"))


@app.route("/batches/<batch_id>")
@login_required
def review_batch(batch_id):
    batch = get_owned_batch_or_404(batch_id)

    try:
        items = prepare_items_for_review(
            batch_id,
            get_batch_items(batch_id)
        )
    except Exception:
        app.logger.exception("Batch items could not be loaded.")
        items = []
        flash("The parcel list could not be loaded.", "error")

    return render_template(
        "batch_review.html",
        batch=batch,
        items=items,
    )


@app.route("/api/batches", methods=["POST"])
@login_required
def api_create_batch():
    data = request.get_json(silent=True) or {}

    try:
        total_items = int(data.get("total_items", 0))
    except (TypeError, ValueError):
        total_items = 0

    if not 1 <= total_items <= MAX_IMAGES:
        return jsonify({
            "error": f"Choose between 1 and {MAX_IMAGES} images."
        }), 400

    batch = create_batch(
        created_by_sub=session["google_sub"],
        created_by_name=session["name"],
        total_items=total_items,
    )

    return jsonify({
        "batch_id": batch["id"],
        "item_url": url_for(
            "api_process_batch_item",
            batch_id=batch["id"],
        ),
        "finish_url": url_for(
            "api_finish_batch_upload",
            batch_id=batch["id"],
        ),
        "review_url": url_for(
            "review_batch",
            batch_id=batch["id"],
        ),
        "status_url": url_for(
            "api_batch_status",
            batch_id=batch["id"],
        ),
    }), 201


@app.route(
    "/api/batches/<batch_id>/items",
    methods=["POST"],
)
@login_required
def api_process_batch_item(batch_id):
    get_owned_batch_or_404(batch_id)
    image = request.files.get("parcel_image")

    if not image or not image.filename:
        return jsonify({"error": "No image was provided."}), 400

    if not allowed_file(image.filename):
        return jsonify({
            "error": "This image format is not supported."
        }), 400

    item_id = create_processing_item(batch_id, image.filename)

    try:
        result = process_uploaded_image(image)
        summary = save_item_result(batch_id, item_id, result)

    except (UnidentifiedImageError, OSError, ValueError):
        message = "The image could not be read."
        summary = save_item_failure(batch_id, item_id, message)
        return jsonify({
            "item_id": item_id,
            "status": "failed",
            "error": message,
            "summary": summary,
        }), 422

    except Exception:
        app.logger.exception(
            "Parcel processing failed for batch %s item %s.",
            batch_id,
            item_id,
        )
        message = "This image could not be processed."
        summary = save_item_failure(batch_id, item_id, message)
        return jsonify({
            "item_id": item_id,
            "status": "failed",
            "error": message,
            "summary": summary,
        }), 500

    return jsonify({
        "item_id": item_id,
        "status": "ready",
        "match_status": result["match"]["status"],
        "summary": summary,
    })


@app.route(
    "/api/batches/<batch_id>/finish-upload",
    methods=["POST"],
)
@login_required
def api_finish_batch_upload(batch_id):
    get_owned_batch_or_404(batch_id)
    summary = finish_batch_upload(batch_id)

    return jsonify({
        "status": summary["status"],
        "summary": summary,
        "review_url": url_for(
            "review_batch",
            batch_id=batch_id,
        ),
    })


@app.route("/api/batches/<batch_id>/status")
@login_required
def api_batch_status(batch_id):
    batch = get_owned_batch_or_404(batch_id)

    return jsonify({
        "status": batch.get("status"),
        "total_items": batch.get("total_items", 0),
        "item_count": batch.get("item_count", 0),
        "ready_count": batch.get("ready_count", 0),
        "failed_count": batch.get("failed_count", 0),
        "confirmed_count": batch.get("confirmed_count", 0),
        "reviewed_count": batch.get("reviewed_count", 0),
    })


@app.route("/api/residents/search")
@login_required
def api_search_residents():
    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return jsonify({"residents": []})

    return jsonify({
        "residents": [
            _safe_resident(resident)
            for resident in search_residents(query)
        ]
    })


@app.route(
    "/batches/<batch_id>/items/<item_id>/edit",
    methods=["POST"],
)
@login_required
def edit_batch_item(batch_id, item_id):
    get_owned_batch_or_404(batch_id)
    get_batch_item(batch_id, item_id)

    detected_name = request.form.get("detected_name", "").strip()
    detected_phone = normalize_phone(
        request.form.get("detected_phone", "")
    )
    building_number = request.form.get(
        "building_number", ""
    ).strip()
    room_number = request.form.get("room_number", "").strip()
    room_letter = request.form.get("room_letter", "").strip().upper()

    match_result = _safe_match(
        match_resident(
            detected_name=detected_name,
            building_number=building_number or None,
            room_number=room_number or None,
            room_letter=room_letter or None,
            phone_number=detected_phone,
        )
    )

    room_display = room_number
    if room_display and room_letter:
        room_display = f"{room_display}{room_letter}"
    if room_display and building_number:
        room_display = f"{building_number}-{room_display}"

    update_batch_item(
        batch_id,
        item_id,
        {
            "detected": {
                "name": detected_name,
                "phone": detected_phone,
                "building_number": building_number,
                "room_number": room_number,
                "room_letter": room_letter,
                "room_display": room_display,
                "ocr_confidence": "human edited",
            },
            "match": match_result,
            "can_save_alias": can_save_alias(
                detected_name,
                match_result.get("resident"),
            ),
            "review_status": (
                "confirmed"
                if match_result.get("status") == "confirmed"
                and match_result.get("resident")
                else "pending"
            ),
            "confirmation_source": (
                "automatic"
                if match_result.get("status") == "confirmed"
                and match_result.get("resident")
                else ""
            ),
        },
    )

    flash("The parcel details were updated and rematched.", "success")
    return redirect(url_for("review_batch", batch_id=batch_id))


@app.route(
    "/batches/<batch_id>/items/<item_id>/select-resident",
    methods=["POST"],
)
@login_required
def select_batch_item_resident(batch_id, item_id):
    get_owned_batch_or_404(batch_id)
    item = get_batch_item(batch_id, item_id)
    resident_id = request.form.get("resident_id", "").strip()
    resident = get_resident_by_student_id(resident_id)

    if not resident:
        flash("That resident could not be found.", "error")
        return redirect(url_for("review_batch", batch_id=batch_id))

    safe_resident = _safe_resident(resident)
    detected_name = item.get("detected", {}).get("name", "")

    update_batch_item(
        batch_id,
        item_id,
        {
            "match": {
                "status": "confirmed",
                "reason": "Resident selected during human review.",
                "resident": safe_resident,
                "scores": {},
                "evidence": ["resident selected by an authorised RA"],
                "candidates": item.get("match", {}).get(
                    "candidates", []
                ),
            },
            "can_save_alias": can_save_alias(
                detected_name,
                safe_resident,
            ),
            "review_status": "confirmed",
            "confirmation_source": "human",
        },
    )

    flash("The resident was selected and confirmed.", "success")
    return redirect(url_for("review_batch", batch_id=batch_id))


@app.route(
    "/batches/<batch_id>/items/<item_id>/confirm",
    methods=["POST"],
)
@login_required
def confirm_batch_item(batch_id, item_id):
    get_owned_batch_or_404(batch_id)
    item = get_batch_item(batch_id, item_id)

    if not item.get("match", {}).get("resident"):
        flash("Choose a resident before confirming this parcel.", "warning")
    else:
        update_batch_item(
            batch_id,
            item_id,
            {
                "review_status": "confirmed",
                "confirmation_source": "human",
            },
        )
        flash("Parcel match confirmed.", "success")

    return redirect(url_for("review_batch", batch_id=batch_id))


@app.route(
    "/batches/<batch_id>/items/<item_id>/unresolved",
    methods=["POST"],
)
@login_required
def mark_batch_item_unresolved(batch_id, item_id):
    get_owned_batch_or_404(batch_id)
    get_batch_item(batch_id, item_id)
    update_batch_item(
        batch_id,
        item_id,
        {
            "review_status": "unresolved",
            "confirmation_source": "human",
        },
    )
    flash("Parcel marked as unresolved.", "warning")
    return redirect(url_for("review_batch", batch_id=batch_id))


@app.route(
    "/batches/<batch_id>/items/<item_id>/alias",
    methods=["POST"],
)
@login_required
def save_batch_item_alias(batch_id, item_id):
    get_owned_batch_or_404(batch_id)
    item = get_batch_item(batch_id, item_id)
    resident_id = request.form.get("resident_id", "").strip()
    alias = request.form.get("alias", "").strip()
    resident = get_resident_by_student_id(resident_id)

    if not resident or not alias:
        abort(400)

    try:
        save_alias(
            alias=alias,
            resident=resident,
            created_by_sub=session["google_sub"],
            created_by_email=session["email"],
        )
    except AliasAlreadyExistsError:
        flash("This alias is already saved.", "warning")
    except InvalidAliasError as error:
        flash(str(error), "error")
    except Exception:
        app.logger.exception("The resident alias could not be saved.")
        flash("The alias could not be saved.", "error")
    else:
        update_batch_item(
            batch_id,
            item_id,
            {
                "can_save_alias": False,
                "review_status": "confirmed",
                "confirmation_source": "human",
            },
        )
        flash("Alias saved and parcel confirmed.", "success")

    return redirect(url_for("review_batch", batch_id=batch_id))


@app.route("/batches/<batch_id>/complete", methods=["POST"])
@login_required
def complete_review_batch(batch_id):
    get_owned_batch_or_404(batch_id)
    items = get_batch_items(batch_id)
    pending = [
        item
        for item in items
        if (
            item.get("processing_status") == "ready"
            and item.get("review_status") == "pending"
        )
    ]

    if pending:
        flash(
            "Review or mark every ready parcel before completing the batch.",
            "warning",
        )
        return redirect(url_for("review_batch", batch_id=batch_id))

    complete_batch(batch_id)
    flash(
        "Batch completed. Its temporary data will be removed shortly.",
        "success",
    )
    return redirect(url_for("batches_dashboard"))


@app.route("/batches/<batch_id>/delete", methods=["POST"])
@login_required
def delete_review_batch(batch_id):
    get_owned_batch_or_404(batch_id)
    delete_batch(batch_id)
    flash("The temporary batch was deleted.", "success")
    return redirect(url_for("batches_dashboard"))


@app.errorhandler(413)
def upload_too_large(_error):
    if request.path.startswith("/api/"):
        return jsonify({
            "error": "The selected image is too large."
        }), 413

    flash("The selected images are too large.", "error")
    return redirect(url_for("home"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port)
