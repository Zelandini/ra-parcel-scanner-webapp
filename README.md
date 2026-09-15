# ParcelMatch — RA Parcel Scanner Webapp

ParcelMatch helps Resident Advisors (RAs) log incoming resident parcels quickly and accurately. An RA photographs a parcel label on their phone, Google's Gemini model extracts the recipient's name, room, and phone number, and the app matches that data against the resident roster so the RA can confirm and log the parcel from any device — phone or desktop.

## How it works

1. **Capture** — An RA opens the app on their phone and photographs one or more parcel labels. Uploads are grouped into a temporary *batch*.
2. **Extract** — Each image is sent to the Gemini API, which extracts the recipient's name, phone number, and CPSV room number (building 831–837, three-digit room, optional unit letter) directly from the label.
3. **Match** — The extracted details are matched against the resident roster (Firestore in production, a local CSV in development) using fuzzy name/phone matching, with support for saved aliases when a resident goes by a different name.
4. **Review** — The RA (or another RA) reviews and confirms each match from the batch review screen, on desktop or phone, before the batch is marked complete.
5. **Clean up** — Original photos are processed in a temporary directory and deleted immediately after extraction. Tracking numbers are never stored, and batches automatically expire (24 hours if incomplete, 1 hour after completion).

See [`docs/batch-workflow.md`](docs/batch-workflow.md) for full details on batch states and privacy behaviour.

## Tech stack

- **Backend:** Flask, Gunicorn
- **AI extraction:** Google Gemini API (`google-genai`)
- **Data store:** Google Firestore (`firebase-admin`), with a local CSV fallback for development
- **Auth:** Google Sign-In, restricted to an approved allow-list of RA email addresses
- **Matching:** RapidFuzz for fuzzy name/phone matching
- **Images:** Pillow + `pillow-heif` (HEIC support from iPhone captures)
- **Companion tool:** a Chrome extension (Manifest V3) for pushing confirmed matches into StarRez

## Project structure

```
app.py                          # Flask app, routes, auth
services/
  parcel_reader.py              # Gemini extraction + schema for parcel labels
  resident_matcher.py           # Fuzzy matching against residents (Firestore/CSV)
  alias_repository.py           # Saved name aliases for residents
  batch_repository.py           # Batch/item lifecycle in Firestore
  batch_logic.py                # Batch state transitions
  image_processing.py           # Upload handling, HEIC conversion
  firestore_client.py           # Firestore connection helper
templates/                      # Jinja templates (capture, review, dashboard, aliases)
static/                         # CSS/JS for the web UI
scripts/import_residents.py     # One-off import of the private resident CSV into Firestore
parcelmatch-starrez-extension/  # Chrome extension to push confirmed residents into StarRez
docs/batch-workflow.md          # Batch lifecycle and privacy behaviour
tests/                          # Pytest unit tests
```

## Setup

### Prerequisites

- Python 3.10+
- A Google Cloud project with Firestore enabled
- A Gemini API key
- A Google OAuth Client ID (for RA sign-in)

### Install

```bash
git clone https://github.com/Zelandini/ra-parcel-scanner-webapp.git
cd ra-parcel-scanner-webapp
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # or requirements.txt for production-only deps
```

### Configure environment

Copy the example env file and fill in your own values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | API key for the Gemini model used to read parcel labels |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID backing Firestore |
| `GOOGLE_CLIENT_ID` | OAuth Client ID used for Google Sign-In |
| `FLASK_SECRET_KEY` | Random secret for Flask session signing |
| `APPROVED_RA_EMAILS` | Comma-separated allow-list of RA emails permitted to sign in |
| `APP_ENV` | `development` or `production` (controls secure cookie settings) |

You'll also need Google Cloud credentials available to the app (e.g. `GOOGLE_APPLICATION_CREDENTIALS` pointing at a service account JSON) so `firebase-admin` can reach Firestore. Never commit credential files, `.env`, or resident data — these are already covered by `.gitignore`.

### Resident data

- **Local development:** place a resident roster at `data/residents.csv` (ignored by git). It must include a `student_id` column.
- **Deployed:** residents live in the Firestore `residents` collection. Import the private CSV from an authenticated machine:

```bash
python scripts/import_residents.py data/residents.csv
```

### Run locally

```bash
python app.py
```

The app runs on `http://localhost:5001` by default (override with the `PORT` env var).

### Run tests

```bash
pytest
```

## Deployment

The included `Procfile` runs the app with Gunicorn, suitable for platforms like Heroku or Cloud Run:

```
web: gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 300 app:app
```

Make sure all environment variables above are set in your hosting platform, and that a Firestore TTL policy is enabled on the `expires_at` field for the `batches` and `items` collections so expired data is cleaned up automatically even if nobody opens the app.

## StarRez Chrome extension

`parcelmatch-starrez-extension/` is a companion Manifest V3 Chrome extension ("ParcelMatch StarRez") that pushes confirmed resident matches into StarRez (`auckland.starrezhousing.com`). Load it via `chrome://extensions` → **Load unpacked** and select the `parcelmatch-starrez-extension` folder.

## Privacy

- Parcel photos are processed in a temporary directory and deleted immediately after extraction — they are never stored.
- Tracking numbers are never stored in batch documents.
- A batch is only visible to the Google account that created it.
- Batches and their items expire automatically (24 hours for incomplete batches, 1 hour after completion).

See [`docs/batch-workflow.md`](docs/batch-workflow.md) for the full data lifecycle.
