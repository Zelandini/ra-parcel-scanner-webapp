import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

from services.firestore_client import get_firestore_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESIDENTS_CSV = PROJECT_ROOT / "data" / "residents.csv"
MAX_CANDIDATES = 3
FUZZY_SURNAME_THRESHOLD = 85
PHONE_THRESHOLD = 85
GIVEN_NAME_THRESHOLD = 75
RESULT_GAP = 10
SURNAME_PARTICLES = {
    "da",
    "das",
    "de",
    "del",
    "della",
    "den",
    "der",
    "di",
    "do",
    "dos",
    "la",
    "las",
    "los",
    "van",
    "von",
}


def normalize_name(value):
    """Return lowercase, accent-free text with consistent spacing."""
    if value is None or pd.isna(value):
        return ""

    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9\s'-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_phone(value):
    """Return a digits-only phone number, using 64 for NZ numbers."""
    if value is None or pd.isna(value):
        return ""

    digits = re.sub(r"\D", "", str(value))
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "64" + digits[1:]
    return digits


def _normalize_room_number(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.lstrip("0") or digits


def _normalize_room_letter(value):
    letters = re.findall(r"[a-zA-Z]", str(value or ""))
    return letters[-1].upper() if letters else ""


@lru_cache(maxsize=1)
def _load_residents(csv_path):
    """
    Load the private local CSV during development. When the CSV is not
    present, load the same resident records from Firestore.
    """
    path = Path(csv_path)

    if path.exists():
        return pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
        )

    documents = (
        get_firestore_database()
        .collection("residents")
        .stream()
    )

    rows = [
        document.to_dict() or {}
        for document in documents
    ]

    if not rows:
        raise RuntimeError(
            "No resident data is available. Import the private "
            "resident CSV into Firestore before deployment."
        )

    return (
        pd.DataFrame(rows)
        .fillna("")
        .astype(str)
    )


def _surname(resident):
    for column in ("last_name", "legal_last_name", "surname"):
        value = normalize_name(resident.get(column, ""))
        if value:
            return value
    return ""


def _full_name_aliases(resident):
    aliases = {
        normalize_name(value)
        for value in (
            resident.get("search_name", ""),
            resident.get("legal_search_name", ""),
            resident.get("full_name", ""),
            resident.get("legal_full_name", ""),
        )
        if normalize_name(value)
    }

    saved_aliases = resident.get("search_aliases", "")
    if not pd.isna(saved_aliases):
        aliases.update(
            normalize_name(alias)
            for alias in str(saved_aliases).split("|")
            if normalize_name(alias)
        )
    return aliases


def _remove_name_part(full_name, name_part):
    full_tokens = normalize_name(full_name).split()
    part_tokens = normalize_name(name_part).split()

    if not full_tokens or not part_tokens:
        return " ".join(full_tokens)

    size = len(part_tokens)
    for index in range(len(full_tokens) - size + 1):
        if full_tokens[index:index + size] == part_tokens:
            return " ".join(full_tokens[:index] + full_tokens[index + size:])
    return " ".join(full_tokens)


def _given_name_aliases(resident):
    surname = _surname(resident)
    aliases = {
        normalize_name(resident.get(column, ""))
        for column in (
            "first_name",
            "preferred_name",
            "legal_first_name",
            "given_name",
        )
        if normalize_name(resident.get(column, ""))
    }

    for full_name in _full_name_aliases(resident):
        given_name = _remove_name_part(full_name, surname)
        if given_name != full_name:
            aliases.add(given_name)
    return aliases


def _contains_name_part(full_name, name_part):
    return _remove_name_part(full_name, name_part) != normalize_name(full_name)


def _name_parts(name, maximum_words):
    tokens = normalize_name(name).split()
    return {
        " ".join(tokens[index:index + size])
        for size in range(1, min(maximum_words, len(tokens)) + 1)
        for index in range(len(tokens) - size + 1)
    }


def _compound_surname_parts(surname):
    """Return meaningful searchable words from a compound surname."""
    return {
        token
        for token in normalize_name(surname).split()
        if token not in SURNAME_PARTICLES and len(token) > 1
    }


def _find_surnames(search_name, residents):
    surnames = {_surname(row) for _, row in residents.iterrows() if _surname(row)}
    exact = {name for name in surnames if _contains_name_part(search_name, name)}

    if exact:
        longest = max(len(name.split()) for name in exact)
        exact_matches = {
            name: {"score": 100.0, "detected_part": name, "match_type": "exact"}
            for name in exact
            if len(name.split()) == longest
        }

        # If the detected surname is one word, also retain compound
        # surnames containing that word.
        if longest == 1:
            detected_surnames = set(exact_matches)
            partial_matches = _partial_surname_matches(
                search_name,
                surnames - detected_surnames,
            )
            if partial_matches:
                return exact_matches | partial_matches, "mixed"

        return exact_matches, "exact"

    # A parcel may contain only one meaningful part of a compound
    # surname. Connecting words are not treated as surnames
    partial_matches = _partial_surname_matches(search_name, surnames)

    if partial_matches:
        return partial_matches, "partial"

    maximum_words = max((len(name.split()) for name in surnames), default=1)
    detected_parts = _name_parts(search_name, maximum_words)
    matches = []

    for surname in surnames:
        detected_part, score = max(
            ((part, fuzz.ratio(part, surname)) for part in detected_parts),
            key=lambda item: item[1],
            default=("", 0),
        )
        matches.append((surname, detected_part, float(score)))

    if not matches:
        return {}, "none"

    best_score = max(score for _, _, score in matches)
    if best_score < FUZZY_SURNAME_THRESHOLD:
        return {}, "none"

    return {
        surname: {
            "score": score,
            "detected_part": detected_part,
            "match_type": "fuzzy",
        }
        for surname, detected_part, score in matches
        if score >= FUZZY_SURNAME_THRESHOLD and score >= best_score - 3
    }, "fuzzy"


def _partial_surname_matches(search_name, surnames):
    matches = {}
    for surname in surnames:
        if len(surname.split()) == 1:
            continue

        matching_parts = {
            part
            for part in _compound_surname_parts(surname)
            if _contains_name_part(search_name, part)
        }
        if matching_parts:
            detected_part = max(matching_parts, key=len)
            matches[surname] = {
                "score": 100.0,
                "detected_part": detected_part,
                "match_type": "partial",
            }
    return matches


def _given_name_score(detected_name, resident):
    aliases = _given_name_aliases(resident)
    if not detected_name or not aliases:
        return 0.0
    return float(
        max(
            max(fuzz.ratio(detected_name, alias), fuzz.token_sort_ratio(detected_name, alias))
            for alias in aliases
        )
    )


def _phone_forms(value):
    phone = normalize_phone(value)
    if not phone:
        return set()

    forms = {phone}
    if phone.startswith("64") and len(phone) > 2:
        national = phone[2:]
        forms.update({national, "0" + national})
    return {form for form in forms if len(form) >= 7}


def _phone_score(detected_phone, resident_phone):
    detected_forms = _phone_forms(detected_phone)
    resident_forms = _phone_forms(resident_phone)
    if not detected_forms or not resident_forms:
        return None
    if detected_forms & resident_forms:
        return 100.0

    detected = normalize_phone(detected_phone)
    resident = normalize_phone(resident_phone)
    if len(detected) >= 8 and len(resident) >= 8 and detected[-8:] == resident[-8:]:
        return 98.0
    if len(detected) >= 7 and len(resident) >= 7 and detected[-7:] == resident[-7:]:
        return 95.0

    score = max(
        fuzz.ratio(first, second)
        for first in detected_forms
        for second in resident_forms
    )
    return round(min(float(score), 94.0), 1)


def _room_evidence(resident, building, number, letter):
    saved_building = normalize_name(resident.get("building", ""))
    saved_room = resident.get("room_short", "")
    checks = {
        "building": None if not building else saved_building == normalize_name(building),
        "room number": None
        if not number
        else _normalize_room_number(saved_room) == _normalize_room_number(number),
        "room letter": None
        if not letter
        else _normalize_room_letter(saved_room) == _normalize_room_letter(letter),
    }
    bonus = sum(
        points
        for label, points in (("building", 10), ("room number", 25), ("room letter", 10))
        if checks[label] is True
    )
    evidence = [f"{label} {'matched' if matched else 'different'}" for label, matched in checks.items() if matched is not None]
    return bonus, any(matched is False for matched in checks.values()), evidence


def _resident_details(resident):
    return {
        "student_id": str(resident.get("student_id", "")),
        "full_name": str(resident.get("full_name", "")),
        "legal_full_name": str(resident.get("legal_full_name", "")),
        "room": str(resident.get("room", "")),
        "building": str(resident.get("building", "")),
        "phone_number": str(resident.get("phone_number", "")),
    }


def _score_candidate(index, resident, search_name, surname_match, parcel):
    detected_given_name = _remove_name_part(search_name, surname_match["detected_part"])
    exact_name = search_name in _full_name_aliases(resident)
    given_score = _given_name_score(detected_given_name, resident)
    phone_score = _phone_score(parcel.get("phone_number"), resident.get("phone_number", ""))
    room_bonus, room_conflict, room_evidence = _room_evidence(
        resident,
        parcel.get("building_number"),
        parcel.get("room_number"),
        parcel.get("room_letter"),
    )

    surname_score = surname_match["score"]
    total = surname_score + (100 if exact_name else given_score) + room_bonus
    if phone_score is not None:
        total += phone_score * 0.8

    surname_evidence = {
        "exact": "surname matched exactly",
        "partial": f'compound surname matched by "{surname_match["detected_part"]}"',
        "fuzzy": f"surname similarity {surname_score:.1f}",
    }
    evidence = [
        surname_evidence[surname_match["match_type"]],
        "full name matched exactly"
        if exact_name
        else f"given-name similarity {given_score:.1f}",
    ]
    if phone_score is not None:
        evidence.append(f"phone similarity {phone_score:.1f}")
    evidence.extend(room_evidence)

    return {
        "index": index,
        "exact_name": exact_name,
        "room_conflict": room_conflict,
        "scores": {
            "surname": round(surname_score, 1),
            "given_name": round(given_score, 1),
            "phone": phone_score,
            "total": round(total, 1),
        },
        "evidence": evidence,
    }


def _choose_result(candidates, surname_match_type):
    exact_names = [
        candidate
        for candidate in candidates
        if (
            candidate["exact_name"]
            and not candidate["room_conflict"]
        )
    ]

    if len(exact_names) == 1:
        return (
            exact_names[0],
            "confirmed",
            "Unique exact full-name match.",
        )

    exact_phones = [
        candidate
        for candidate in candidates
        if (
            candidate["scores"]["phone"] == 100
            and not candidate["room_conflict"]
        )
    ]

    if (
        surname_match_type in {"exact", "mixed"}
        and len(exact_phones) == 1
    ):
        return (
            exact_phones[0],
            "confirmed",
            "Unique exact phone match with matching surname evidence.",
        )

    best = candidates[0]

    second_total = (
        candidates[1]["scores"]["total"]
        if len(candidates) > 1
        else 0
    )

    clear_lead = (
        best["scores"]["total"] - second_total
        >= RESULT_GAP
    )

    supported = (
        best["scores"]["given_name"]
        >= GIVEN_NAME_THRESHOLD
        or (
            best["scores"]["phone"] or 0
        ) >= PHONE_THRESHOLD
    )

    if clear_lead and supported:
        return (
            best,
            "possible",
            "One candidate has a clear lead but requires confirmation.",
        )

    return (
        best,
        "ambiguous",
        "The available evidence cannot safely identify one resident.",
    )


def _empty_result(detected_name, reason):
    return {
        "status": "not_found",
        "detected_name": detected_name,
        "reason": reason,
        "resident": None,
        "surname_match_type": "none",
        "scores": {},
        "evidence": [],
        "candidates": [],
    }


def search_csv(search_name, building_number=None, room_number=None, room_letter=None, phone_number=None):
    """Return a surname-first resident match without printing anything."""
    detected_name = str(search_name or "").strip()
    normalized_name = normalize_name(detected_name)
    if not normalized_name:
        return _empty_result(detected_name, "No recipient name was detected.")

    residents = _load_residents(str(RESIDENTS_CSV))
    surname_matches, surname_match_type = _find_surnames(normalized_name, residents)
    if not surname_matches:
        return _empty_result(detected_name, "No reliable surname match was found.")

    parcel = {
        "building_number": building_number,
        "room_number": room_number,
        "room_letter": room_letter,
        "phone_number": phone_number,
    }
    candidates = [
        _score_candidate(index, resident, normalized_name, surname_matches[_surname(resident)], parcel)
        for index, resident in residents.iterrows()
        if _surname(resident) in surname_matches
    ]
    if not candidates:
        return _empty_result(detected_name, "No residents were found in the surname candidate pool.")

    candidates.sort(key=lambda candidate: candidate["scores"]["total"], reverse=True)
    selected, status, reason = _choose_result(candidates, surname_match_type)

    output_candidates = []
    for candidate in candidates[:MAX_CANDIDATES]:
        output_candidates.append(
            {
                "resident": _resident_details(residents.loc[candidate["index"]]),
                "scores": candidate["scores"],
                "evidence": candidate["evidence"],
            }
        )

    return {
        "status": status,
        "detected_name": detected_name,
        "reason": reason,
        "resident": _resident_details(residents.loc[selected["index"]]),
        "surname_match_type": surname_match_type,
        "scores": selected["scores"],
        "evidence": selected["evidence"],
        "candidates": output_candidates,
    }

def get_resident_by_student_id(student_id):
    """
    Return one resident from the local CSV using their student ID.
    """
    searched_id = str(student_id or "").strip()

    if not searched_id:
        return None

    residents = _load_residents(
        str(RESIDENTS_CSV)
    )

    matching_residents = residents[
        residents["student_id"].astype(str).str.strip()
        == searched_id
    ]

    if matching_residents.empty:
        return None

    return _resident_details(
        matching_residents.iloc[0]
    )