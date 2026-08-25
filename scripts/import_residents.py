import argparse
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.firestore_client import get_firestore_database


def import_residents(csv_path):
    residents = pd.read_csv(
        csv_path,
        dtype=str,
        keep_default_na=False,
    )

    if "student_id" not in residents.columns:
        raise ValueError(
            "The CSV must contain a student_id column."
        )

    database = get_firestore_database()
    batch = database.batch()
    pending_writes = 0
    imported = 0

    for row in residents.to_dict(orient="records"):
        resident_id = str(
            row.get("student_id", "")
        ).strip()

        if not resident_id:
            continue

        clean_row = {
            str(key): str(value).strip()
            for key, value in row.items()
        }

        reference = (
            database
            .collection("residents")
            .document(resident_id)
        )

        batch.set(
            reference,
            clean_row,
            merge=True,
        )

        pending_writes += 1
        imported += 1

        if pending_writes == 400:
            batch.commit()
            batch = database.batch()
            pending_writes = 0

    if pending_writes:
        batch.commit()

    return imported


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Import the private resident CSV into Firestore."
        )
    )

    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to the private residents CSV.",
    )

    arguments = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    imported = import_residents(
        arguments.csv_path
    )

    print(
        f"Imported {imported} resident records."
    )


if __name__ == "__main__":
    main()
