import os

import firebase_admin
from firebase_admin import firestore


def get_firestore_database():
    """
    Return the application's Firestore database connection.

    Local development uses Application Default Credentials.
    Cloud Run will use its attached service account.
    """
    try:
        firebase_app = firebase_admin.get_app()

    except ValueError:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")

        if not project_id:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT is not configured."
            )

        firebase_app = firebase_admin.initialize_app(
            options={
                "projectId": project_id,
            }
        )

    return firestore.client(app=firebase_app)