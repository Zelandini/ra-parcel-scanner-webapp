from services.batch_logic import calculate_batch_summary


def test_processing_batch_reports_current_counts():
    summary = calculate_batch_summary(
        {
            "status": "processing",
            "upload_finished": False,
            "total_items": 3,
        },
        [
            {
                "processing_status": "ready",
                "review_status": "confirmed",
            },
            {
                "processing_status": "failed",
                "review_status": "unresolved",
            },
        ],
    )

    assert summary == {
        "item_count": 2,
        "ready_count": 1,
        "failed_count": 1,
        "confirmed_count": 1,
        "reviewed_count": 2,
        "status": "processing",
    }


def test_finished_full_upload_is_ready_for_review():
    summary = calculate_batch_summary(
        {
            "status": "processing",
            "upload_finished": True,
            "total_items": 2,
        },
        [
            {"processing_status": "ready", "review_status": "pending"},
            {"processing_status": "ready", "review_status": "pending"},
        ],
    )

    assert summary["status"] == "ready_for_review"


def test_finished_partial_upload_is_marked_incomplete():
    summary = calculate_batch_summary(
        {
            "status": "processing",
            "upload_finished": True,
            "total_items": 3,
        },
        [
            {"processing_status": "ready", "review_status": "pending"},
        ],
    )

    assert summary["status"] == "upload_incomplete"


def test_completed_status_is_preserved():
    summary = calculate_batch_summary(
        {
            "status": "completed",
            "upload_finished": True,
            "total_items": 1,
        },
        [
            {"processing_status": "ready", "review_status": "confirmed"},
        ],
    )

    assert summary["status"] == "completed"
