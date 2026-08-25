def calculate_batch_summary(batch, items):
    """Calculate batch counts and status without database access."""
    item_count = len(items)
    ready_count = sum(
        item.get("processing_status") == "ready"
        for item in items
    )
    failed_count = sum(
        item.get("processing_status") == "failed"
        for item in items
    )
    confirmed_count = sum(
        item.get("review_status") == "confirmed"
        for item in items
    )
    reviewed_count = sum(
        item.get("review_status") in {"confirmed", "unresolved"}
        for item in items
    )

    status = batch.get("status", "processing")

    if status != "completed":
        if (
            batch.get("upload_finished")
            and item_count >= int(batch.get("total_items", 0))
        ):
            status = "ready_for_review"
        elif batch.get("upload_finished"):
            status = "upload_incomplete"
        else:
            status = "processing"

    return {
        "item_count": item_count,
        "ready_count": ready_count,
        "failed_count": failed_count,
        "confirmed_count": confirmed_count,
        "reviewed_count": reviewed_count,
        "status": status,
    }
