# Temporary batch workflow

ParcelMatch stores extracted parcel results temporarily so an RA can capture
photographs on a phone and review the results later from a desktop.

## Privacy behaviour

- Original photographs are converted and processed in a temporary directory.
- The temporary directory is deleted after each image is processed.
- Tracking numbers are not stored in batch documents.
- A batch is visible only to the Google account that created it.
- Active batches receive an `expires_at` value 24 hours after creation.
- Completed batches receive an `expires_at` value one hour after completion.
- Opening the capture page or dashboard removes expired batches and items.

For automatic cleanup even when nobody opens the app, enable a Firestore TTL
policy on the `expires_at` field for both collection groups:

- `batches`
- `items`

The item TTL is necessary because deleting a Firestore parent document does not
automatically delete its subcollection documents.

## Batch states

- `processing`: the phone is still uploading images.
- `ready_for_review`: every selected image has produced a stored result.
- `upload_incomplete`: the upload finished, but one or more requests never
  reached the server.
- `completed`: human checking is finished and cleanup is pending.

## Local and deployed resident data

Local development continues to use the ignored `data/residents.csv` file. A
deployed instance falls back to the Firestore `residents` collection. Import the
private file from an authenticated local machine with:

```bash
python scripts/import_residents.py data/residents.csv
```

Never commit the resident CSV, parcel photographs, `.env`, or Google credential
files.
