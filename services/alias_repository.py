import hashlib
import re

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter

from services.firestore_client import get_firestore_database
from services.resident_matcher import normalize_name


class AliasAlreadyExistsError(Exception):
    pass


class InvalidAliasError(Exception):
    pass


class AliasNotFoundError(Exception):
    pass


def validate_alias(alias):
    cleaned_alias = re.sub(
        r"\s+",
        " ",
        str(alias or ""),
    ).strip()

    if len(cleaned_alias) < 2:
        raise InvalidAliasError(
            "The alias must contain at least two characters."
        )

    if len(cleaned_alias) > 100:
        raise InvalidAliasError(
            "The alias cannot exceed 100 characters."
        )

    if not any(character.isalpha() for character in cleaned_alias):
        raise InvalidAliasError(
            "The alias must contain at least one letter."
        )

    return cleaned_alias


def save_alias(
    alias,
    resident,
    created_by_sub,
    created_by_email,
):
    cleaned_alias = validate_alias(alias)
    normalized_alias = normalize_name(cleaned_alias)

    registered_names = {
        normalize_name(resident.get("full_name")),
        normalize_name(resident.get("legal_full_name")),
    }

    if normalized_alias in registered_names:
        raise InvalidAliasError(
            "This is already the resident's official name."
        )

    document_key = (
        f"{resident['student_id']}|{normalized_alias}"
    )

    document_id = hashlib.sha256(
        document_key.encode("utf-8")
    ).hexdigest()

    alias_document = {
        "alias": cleaned_alias,
        "normalized_alias": normalized_alias,
        "resident_id": resident["student_id"],
        "created_by_sub": created_by_sub,
        "created_by_email": created_by_email,
        "created_at": firestore.SERVER_TIMESTAMP,
        "active": True,
    }

    database = get_firestore_database()

    document_reference = (
        database
        .collection("aliases")
        .document(document_id)
    )

    try:
        document_reference.create(alias_document)

    except AlreadyExists as error:
        existing = document_reference.get().to_dict() or {}

        if existing.get("active") is False:
            document_reference.set(
                {
                    **alias_document,
                    "reactivated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )

            return {
                "id": document_id,
                **alias_document,
            }

        raise AliasAlreadyExistsError(
            "This alias is already saved for this resident."
        ) from error

    return {
        "id": document_id,
        **alias_document,
    }

def find_active_alias_resident_ids(alias):
    """
    Return resident IDs connected to an active, normalized alias.

    More than one ID is returned when the same alias belongs to
    multiple residents, allowing the caller to avoid unsafe automatic
    confirmation.
    """
    normalized_alias = normalize_name(alias)

    if not normalized_alias:
        return []

    database = get_firestore_database()

    documents = (
        database
        .collection("aliases")
        .where(
            filter=FieldFilter(
                "normalized_alias",
                "==",
                normalized_alias,
            )
        )
        .stream()
    )

    resident_ids = {
        str(document_data.get("resident_id", "")).strip()
        for document in documents
        for document_data in [document.to_dict() or {}]
        if (
            document_data.get("active") is True
            and str(
                document_data.get("resident_id", "")
            ).strip()
        )
    }

    return sorted(resident_ids)


def get_active_aliases_for_resident(resident_id):
    """Return active alias labels for one resident."""
    searched_id = str(resident_id or "").strip()

    if not searched_id:
        return []

    documents = (
        get_firestore_database()
        .collection("aliases")
        .where(
            filter=FieldFilter(
                "resident_id",
                "==",
                searched_id,
            )
        )
        .stream()
    )

    aliases = {
        str(data.get("alias", "")).strip()
        for document in documents
        for data in [document.to_dict() or {}]
        if (
            data.get("active") is True
            and str(data.get("alias", "")).strip()
        )
    }

    return sorted(aliases, key=str.casefold)


def list_active_aliases():
    """Return every active alias for the management page."""
    documents = (
        get_firestore_database()
        .collection("aliases")
        .stream()
    )

    aliases = []

    for document in documents:
        data = document.to_dict() or {}

        if data.get("active") is not True:
            continue

        aliases.append({
            "id": document.id,
            "alias": str(data.get("alias", "")).strip(),
            "normalized_alias": str(
                data.get("normalized_alias", "")
            ),
            "resident_id": str(
                data.get("resident_id", "")
            ).strip(),
            "created_at": data.get("created_at"),
        })

    aliases.sort(
        key=lambda item: (
            item["alias"].casefold(),
            item["resident_id"],
        )
    )
    return aliases


def get_alias(alias_id):
    document = (
        get_firestore_database()
        .collection("aliases")
        .document(alias_id)
        .get()
    )

    if not document.exists:
        raise AliasNotFoundError("The alias was not found.")

    return {
        "id": document.id,
        **(document.to_dict() or {}),
    }


def deactivate_alias(
    alias_id,
    changed_by_sub,
    changed_by_email,
):
    alias = get_alias(alias_id)

    if alias.get("active") is not True:
        raise AliasNotFoundError("The alias is no longer active.")

    (
        get_firestore_database()
        .collection("aliases")
        .document(alias_id)
        .set(
            {
                "active": False,
                "deactivated_at": firestore.SERVER_TIMESTAMP,
                "deactivated_by_sub": changed_by_sub,
                "deactivated_by_email": changed_by_email,
            },
            merge=True,
        )
    )

    return alias


def replace_alias(
    alias_id,
    new_alias,
    resident,
    changed_by_sub,
    changed_by_email,
):
    existing = get_alias(alias_id)

    if existing.get("active") is not True:
        raise AliasNotFoundError("The alias is no longer active.")

    if str(existing.get("resident_id", "")) != str(
        resident.get("student_id", "")
    ):
        raise InvalidAliasError(
            "The alias does not belong to that resident."
        )

    cleaned_alias = validate_alias(new_alias)
    normalized_alias = normalize_name(cleaned_alias)

    if normalized_alias == existing.get("normalized_alias"):
        (
            get_firestore_database()
            .collection("aliases")
            .document(alias_id)
            .set(
                {
                    "alias": cleaned_alias,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "updated_by_sub": changed_by_sub,
                    "updated_by_email": changed_by_email,
                },
                merge=True,
            )
        )
        return {**existing, "alias": cleaned_alias}

    replacement = save_alias(
        alias=cleaned_alias,
        resident=resident,
        created_by_sub=changed_by_sub,
        created_by_email=changed_by_email,
    )

    deactivate_alias(
        alias_id=alias_id,
        changed_by_sub=changed_by_sub,
        changed_by_email=changed_by_email,
    )

    return replacement
