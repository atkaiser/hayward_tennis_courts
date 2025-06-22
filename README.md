# Hayward Tennis Courts Sync

This project syncs tennis court reservations from the Hayward Rec website into Google Calendar. The script pulls reservation data, converts booked slots into events and then creates or removes events on dedicated calendars per location.

## Features
- Fetches reservations for the next 80 days and only updates calendars when bookings change.
- Supports a `--dry-run` mode and adjustable `--throttle` delay.
- Calendar IDs for each location are hardcoded in `hayward_tennis_sync.py`.

## Google API Setup
Before running the sync you must:
1. Create a Google Cloud project and enable the Calendar API.
2. Create a service account and download the JSON credentials file.
3. Share each calendar with the service account email and grant **Make changes to events** permission.

These steps mirror the instructions in `spec.md`.

## Installation
Use Python 3.8+ and install dependencies:
```bash
pip install -r requirements.txt
```

## Usage
Run the sync script with your credentials file:
```bash
python hayward_tennis_sync.py --credentials-path /path/to/creds.json
```
Additional flags:
- `--dry-run` to log planned changes without modifying calendars.
- `--throttle` to control delay between requests (default is 5 seconds).

## Testing
Unit tests are provided and can be run with:
```bash
pytest
```
