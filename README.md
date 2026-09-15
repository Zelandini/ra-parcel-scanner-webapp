# ParcelMatch — RA Parcel Scanner

ParcelMatch is a Flask web application designed to help Resident Advisors process incoming parcels more efficiently.

Instead of manually reading parcel labels and searching for residents, ParcelMatch uses Gemini Vision to extract delivery information from parcel images and matches the detected recipient against resident records.

Confirmed residents can then be transferred into the StarRez Directory using a companion Chrome extension, reducing the amount of manual searching required during the parcel logging process.

Human review remains part of the workflow whenever a match cannot be identified confidently.

## Features

* Upload parcel images from desktop or mobile
* Process up to 20 parcel images per batch
* Extract recipient details using Gemini Vision
* Validate AI output using Pydantic
* Match parcel recipients against resident records
* Use name, room and phone information as matching evidence
* Support preferred names, legal names and saved aliases
* Separate confirmed, possible, ambiguous and unresolved matches
* Manually search for and select residents when required
* Edit extracted parcel information and rerun matching
* Save confirmed aliases to improve future matching
* Review uploaded batches from another device
* Google Sign-In with an approved-user allowlist
* Temporary batch storage using Firestore
* Automatically transfer confirmed residents into StarRez using a Chrome extension

---

## Workflow

```text
Parcel Images
      ↓
Image Preparation
      ↓
Gemini Vision
      ↓
Structured Parcel Information
      ↓
Resident Matching
      ↓
Confirmed / Possible / Ambiguous / Not Found
      ↓
RA Review
      ↓
Confirmed Residents
      ↓
ParcelMatch StarRez Extension
      ↓
StarRez Directory
```

The aim is not to allow AI to make the final operational decision by itself.

Gemini is primarily responsible for reading the parcel label. Matching and review are handled separately so uncertain results can be checked by an RA.

---

## Parcel Recognition

Parcel images are processed before being sent to Gemini.

Supported formats include:

```text
JPEG
PNG
WEBP
HEIC
HEIF
```

Images are converted into a consistent JPEG format before processing.

Gemini extracts structured fields such as:

* recipient name
* phone number
* building number
* room number
* room letter
* tracking number
* extraction confidence

Pydantic is used to validate the structure of Gemini's response before it enters the matching system.

---

## Resident Matching

ParcelMatch uses deterministic matching logic after Gemini has extracted the information.

The matcher considers several forms of evidence including:

* surname matching
* given-name similarity
* exact full-name matches
* preferred names
* legal names
* saved aliases
* room number
* building number
* room letter
* phone number

RapidFuzz is used where fuzzy comparison is required.

A strong match may be automatically classified as confirmed, while less certain results are presented to the RA for review.

Possible outcomes include:

```text
Confirmed
Possible
Ambiguous
Not Found
```

The RA can manually select a resident if the automatic matcher cannot safely determine the correct person.

---

## Saved Aliases

Parcel labels do not always use the same name stored in the resident database.

For example, a parcel may use:

* a preferred name
* a shortened name
* an alternative spelling
* another name regularly used by the resident

After manually confirming a match, an authorised RA can save the detected parcel name as an alias.

Future parcels using the same alias can then be matched automatically.

Aliases are stored separately from the resident dataset and can be managed through the application.

---

## Batch Processing

ParcelMatch supports batches of up to **20 images**.

This allows an RA to photograph several parcels using a phone and review the processed results later from another device.

Batch states include:

```text
processing
ready_for_review
upload_incomplete
completed
```

Each parcel in the batch can then be:

* confirmed
* manually matched
* edited and rematched
* marked unresolved

A batch can only be completed once all successfully processed parcels have been reviewed.

---

# ParcelMatch → StarRez Extension

ParcelMatch includes a companion Chrome extension that connects the final ParcelMatch review workflow with the StarRez Directory.

Normally, after identifying parcel recipients, an RA would still need to manually search for each resident inside StarRez.

The extension automates this step.

## How It Works

After parcel matches have been reviewed:

```text
ParcelMatch Review Page
        ↓
Confirmed Residents
        ↓
Chrome Extension
        ↓
Student IDs collected
        ↓
Existing StarRez Directory tab
        ↓
Residents searched
        ↓
Matching residents selected
```

The extension reads only residents that have already been confirmed through ParcelMatch.

It then communicates with an existing StarRez Directory tab and automatically searches for each corresponding resident.

---

## StarRez Extension Features

The extension:

* reads confirmed residents from the ParcelMatch batch review page
* collects their student IDs
* removes duplicate IDs
* supports up to 20 residents at a time
* detects an existing StarRez Directory tab
* searches each student ID in StarRez
* selects the corresponding resident checkbox
* reports how many residents were successfully selected
* reports residents that could not be found
* only runs on the configured ParcelMatch and StarRez pages

The extension does **not** automatically approve uncertain ParcelMatch results.

Only residents that have already been confirmed are transferred to StarRez.

---

## Tech Stack

### Backend

* Python
* Flask
* Pydantic
* pandas
* RapidFuzz

### AI

* Google Gemini Vision API

### Authentication

* Google Sign-In
* Approved-user allowlist

### Database

* Firebase Firestore

### Frontend

* HTML
* CSS
* JavaScript
* Jinja2

### StarRez Integration

* Chrome Extension
* Manifest V3
* JavaScript
* Chrome Tabs API
* Content scripts

### Deployment

* Google Cloud Run
* Gunicorn

---

## Project Structure

```text
ra-parcel-scanner-webapp/
├── app.py
│
├── services/
│   ├── alias_repository.py
│   ├── batch_logic.py
│   ├── batch_repository.py
│   ├── firestore_client.py
│   ├── image_processing.py
│   ├── parcel_reader.py
│   └── resident_matcher.py
│
├── templates/
├── static/
├── scripts/
├── tests/
├── docs/
│
├── requirements.txt
├── requirements-dev.txt
├── Procfile
├── .env.example
└── README.md
```

The StarRez Chrome extension is maintained as a companion component to the web application.

---

# Local Setup

## 1. Clone the repository

```bash
git clone https://github.com/Zelandini/ra-parcel-scanner-webapp.git
cd ra-parcel-scanner-webapp
```

## 2. Create a virtual environment

```bash
python -m venv .venv
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Windows:

```bash
.venv\Scripts\activate
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Configure environment variables

Create a local `.env` file based on:

```text
.env.example
```

Example:

```env
GEMINI_API_KEY=your-gemini-api-key
GOOGLE_CLOUD_PROJECT=your-google-cloud-project
GOOGLE_CLIENT_ID=your-google-client-id
FLASK_SECRET_KEY=your-random-secret
APPROVED_RA_EMAILS=ra1@example.com,ra2@example.com
APP_ENV=development
```

Never commit the real `.env` file.

## 5. Run the application

```bash
python app.py
```

The development server runs by default at:

```text
http://localhost:5001
```

---

# Resident Data

Resident information is intentionally excluded from the public repository.

During local development, ParcelMatch looks for:

```text
data/residents.csv
```

In the deployed application, resident records can instead be loaded from Firestore.

Resident data can be imported from an authenticated machine using:

```bash
python scripts/import_residents.py data/residents.csv
```

The resident CSV should **never** be committed to the repository.

---

# Privacy

ParcelMatch processes private resident and delivery information, so data minimisation is an important part of the application.

Do **not** commit:

```text
data/residents.csv
.env
parcel photographs
Google credential files
resident exports
other personally identifiable resident information
```

### Parcel Images

Uploaded parcel images are processed using temporary storage.

The temporary image directory is removed after processing.

### Batch Data

Temporary batch results are stored in Firestore so an RA can upload parcels from one device and review them from another.

Active and completed batches have expiration times so temporary information can be automatically removed.

### Tracking Numbers

Tracking numbers extracted during parcel recognition are not stored in temporary batch documents.

### Access Control

Batch information is associated with the Google account that created the batch.

The application also uses an approved email allowlist to restrict access to authorised users.

For more information, see:

```text
docs/batch-workflow.md
```

---

# Deployment

ParcelMatch is designed to run on Google Cloud Run.

Gunicorn is used as the production application server:

```bash
gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 300 app:app
```

Cloud Run provides the application's runtime environment while Firestore stores the data required by the deployed application.

The Cloud Run service account can be used to authenticate with Google Cloud services without storing service-account credentials inside the repository.

---

# Why ParcelMatch?

Parcel processing can involve several repetitive steps:

```text
Read parcel label
→ identify recipient
→ search resident records
→ confirm resident
→ search StarRez
→ select resident
→ repeat
```

ParcelMatch reduces this to:

```text
Photograph parcels
→ review suggested matches
→ confirm
→ transfer confirmed residents to StarRez
```

The project combines AI-assisted visual extraction with deterministic matching and human review.

AI handles the part it is useful for — understanding inconsistent parcel labels — while the application retains explicit matching rules and human confirmation for decisions involving resident information.
