from services.resident_matcher import (
    _choose_result,
    normalize_name,
    normalize_phone,
)


def test_normalize_name_removes_accents_and_spacing():
    assert normalize_name("  José   Example  ") == "jose example"


def test_normalize_phone_converts_nz_national_number():
    assert normalize_phone("021 234 5678") == "64212345678"


def test_unique_exact_name_is_confirmed_for_mixed_surname():
    candidate = {
        "exact_name": True,
        "room_conflict": False,
        "scores": {
            "phone": None,
            "given_name": 100.0,
            "total": 200.0,
        },
    }

    selected, status, reason = _choose_result(
        [candidate],
        "mixed",
    )

    assert selected is candidate
    assert status == "confirmed"
    assert reason == "Unique exact full-name match."


def test_room_conflict_prevents_exact_name_confirmation():
    candidate = {
        "exact_name": True,
        "room_conflict": True,
        "scores": {
            "phone": None,
            "given_name": 100.0,
            "total": 200.0,
        },
    }

    _, status, _ = _choose_result(
        [candidate],
        "exact",
    )

    assert status == "possible"
