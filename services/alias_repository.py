import hashlib
import re

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from services.firestore_client import get_firestore_database
from services.resident_matcher import normalize_name


class AliasAlreadyExistsError(Exception):
    pass


class InvalidAliasError(Exception):
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

    official_name = normalize_name(
        resident.get("full_name")
    )

    if normalized_alias == official_name:
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
        raise AliasAlreadyExistsError(
            "This alias is already saved for this resident."
        ) from error

    return {
        "id": document_id,
        **alias_document,
    }