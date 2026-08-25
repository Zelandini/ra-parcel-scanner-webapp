from datetime import datetime, timedelta, timezone

from google.cloud.firestore_v1.base_query import FieldFilter

from services.batch_logic import calculate_batch_summary
from services.firestore_client import get_firestore_database


ACTIVE_BATCH_HOURS = 24
COMPLETED_BATCH_HOURS = 1


class BatchNotFoundError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _with_id(document):
    data = document.to_dict() or {}
    data["id"] = document.id
    return data


def create_batch(created_by_sub, created_by_name, total_items):
    database = get_firestore_database()
    reference = database.collection("batches").document()
    now = _now()

    data = {
        "created_by_sub": created_by_sub,
        "created_by_name": created_by_name,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + timedelta(hours=ACTIVE_BATCH_HOURS),
        "status": "processing",
        "upload_finished": False,
        "total_items": int(total_items),
        "item_count": 0,
        "ready_count": 0,
        "failed_count": 0,
        "confirmed_count": 0,
        "reviewed_count": 0,
    }

    reference.set(data)
    return {"id": reference.id, **data}


def get_batch(batch_id, owner_sub):
    document = (
        get_firestore_database()
        .collection("batches")
        .document(batch_id)
        .get()
    )

    if not document.exists:
        raise BatchNotFoundError("The batch was not found.")

    batch = _with_id(document)

    if batch.get("created_by_sub") != owner_sub:
        raise BatchNotFoundError("The batch was not found.")

    return batch


def list_batches(owner_sub, include_completed=False):
    documents = (
        get_firestore_database()
        .collection("batches")
        .where(
            filter=FieldFilter(
                "created_by_sub",
                "==",
                owner_sub,
            )
        )
        .stream()
    )

    batches = [_with_id(document) for document in documents]

    if not include_completed:
        batches = [
            batch
            for batch in batches
            if batch.get("status") != "completed"
        ]

    batches.sort(
        key=lambda batch: batch.get("updated_at") or _now(),
        reverse=True,
    )
    return batches


def create_processing_item(batch_id, filename):
    database = get_firestore_database()
    batch_reference = database.collection("batches").document(batch_id)
    batch_data = batch_reference.get().to_dict() or {}
    reference = (
        batch_reference
        .collection("items")
        .document()
    )
    now = _now()

    data = {
        "filename": filename,
        "processing_status": "processing",
        "review_status": "pending",
        "created_at": now,
        "updated_at": now,
        "expires_at": batch_data.get(
            "expires_at",
            now + timedelta(hours=ACTIVE_BATCH_HOURS),
        ),
    }

    reference.set(data)
    return reference.id


def save_item_result(batch_id, item_id, result):
    match = result.get("match", {})
    automatically_confirmed = (
        match.get("status") == "confirmed"
        and bool(match.get("resident"))
    )

    (
        get_firestore_database()
        .collection("batches")
        .document(batch_id)
        .collection("items")
        .document(item_id)
        .set(
            {
                **result,
                "processing_status": "ready",
                "review_status": (
                    "confirmed"
                    if automatically_confirmed
                    else "pending"
                ),
                "confirmation_source": (
                    "automatic"
                    if automatically_confirmed
                    else ""
                ),
                "updated_at": _now(),
            },
            merge=True,
        )
    )
    return refresh_batch_summary(batch_id)


def save_item_failure(batch_id, item_id, message):
    (
        get_firestore_database()
        .collection("batches")
        .document(batch_id)
        .collection("items")
        .document(item_id)
        .set(
            {
                "processing_status": "failed",
                "review_status": "unresolved",
                "error": message,
                "updated_at": _now(),
            },
            merge=True,
        )
    )
    return refresh_batch_summary(batch_id)


def get_batch_items(batch_id):
    documents = (
        get_firestore_database()
        .collection("batches")
        .document(batch_id)
        .collection("items")
        .stream()
    )

    items = [_with_id(document) for document in documents]
    items.sort(key=lambda item: item.get("created_at") or _now())
    return items


def get_batch_item(batch_id, item_id):
    document = (
        get_firestore_database()
        .collection("batches")
        .document(batch_id)
        .collection("items")
        .document(item_id)
        .get()
    )

    if not document.exists:
        raise BatchNotFoundError("The parcel item was not found.")

    return _with_id(document)


def update_batch_item(
    batch_id,
    item_id,
    updates,
    refresh=True,
):
    reference = (
        get_firestore_database()
        .collection("batches")
        .document(batch_id)
        .collection("items")
        .document(item_id)
    )

    reference.set(
        {
            **updates,
            "updated_at": _now(),
        },
        merge=True,
    )

    if refresh:
        refresh_batch_summary(batch_id)

    return get_batch_item(batch_id, item_id)


def refresh_batch_summary(batch_id):
    database = get_firestore_database()
    batch_reference = database.collection("batches").document(batch_id)
    batch_document = batch_reference.get()

    if not batch_document.exists:
        raise BatchNotFoundError("The batch was not found.")

    batch = batch_document.to_dict() or {}
    items = get_batch_items(batch_id)
    summary = {
        **calculate_batch_summary(batch, items),
        "updated_at": _now(),
    }

    batch_reference.set(summary, merge=True)
    return summary


def finish_batch_upload(batch_id):
    (
        get_firestore_database()
        .collection("batches")
        .document(batch_id)
        .set(
            {
                "upload_finished": True,
                "updated_at": _now(),
            },
            merge=True,
        )
    )
    return refresh_batch_summary(batch_id)


def complete_batch(batch_id):
    now = _now()
    expires_at = now + timedelta(hours=COMPLETED_BATCH_HOURS)
    database = get_firestore_database()
    batch_reference = database.collection("batches").document(batch_id)

    batch_reference.set(
        {
            "status": "completed",
            "updated_at": now,
            "expires_at": expires_at,
        },
        merge=True,
    )

    for item in batch_reference.collection("items").stream():
        item.reference.set(
            {"expires_at": expires_at},
            merge=True,
        )


def delete_batch(batch_id):
    database = get_firestore_database()
    batch_reference = database.collection("batches").document(batch_id)

    for item in batch_reference.collection("items").stream():
        item.reference.delete()

    batch_reference.delete()


def cleanup_expired_batches(owner_sub):
    now = _now()

    for batch in list_batches(owner_sub, include_completed=True):
        expires_at = batch.get("expires_at")

        if expires_at and expires_at <= now:
            delete_batch(batch["id"])
