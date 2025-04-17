import argparse
import datetime
import json
import logging
import os
import sys
import time
import requests
from typing import List
from zoneinfo import ZoneInfo

# Constants
TIMEZONE: str = 'America/Los_Angeles'
CALENDAR_IDS: List[str] = ['calendar1@example.com', 'calendar2@example.com']
DEFAULT_THROTTLE: float = 1.5

def get_sync_date_range(num_days: int = 80) -> List[str]:
    """
    Calculates and returns a list of date strings for the sync range.
    Start date is today + 2 days, end date is today + 81 days (80 days total).
    """
    start_date = datetime.date.today() + datetime.timedelta(days=2)
    # Create a list of 80 days starting from start_date
    return [(start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]
    
def Workspace_hayward_data(date_str: str, throttle_seconds: float) -> bytes:
    """
    Fetches data from the Hayward API for a given date with throttling.

    Constructs the URL using the provided date_str.
    Implements throttling using time.sleep(throttle_seconds) before making the request.
    
    Returns the raw response content (JSON).
    """
    # Construct the URL for the given date. For now, assume the API accepts a
    # query parameter 'date' formatted as YYYY-MM-DD.
    url = f"https://api.hayward.example.com/schedule?date={date_str}"
    # Throttle
    time.sleep(throttle_seconds)
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching data from Hayward API: {e}")
        sys.exit(1)
    return response.content

def parse_reservation_data(json_data: bytes) -> dict:
    """
    Parses the raw JSON data from the Hayward API to extract reservation data.

    The expected JSON structure is determined by scanning through locations, courts, and time slots.
    It filters and returns a dictionary structured as:
    
    {
        "YYYY-MM-DD": {
            "Mervin": {
                "Court 1": {"09:00": True, "09:30": True, ... },
                "Court 2": {"09:00": False, ...}
            },
            "Bay": { ... }
        }
    }
    
    Raises:
        ValueError: if the JSON data is invalid or missing required keys.
    """
    try:
        data = json.loads(json_data.decode("utf-8"))
    except Exception as e:
        raise ValueError("Failed to parse JSON data") from e

    result = {}
    if "date" not in data or "locations" not in data:
        raise ValueError("JSON data missing required 'date' or 'locations' keys")
    date_str = data["date"]
    result[date_str] = {}
    locations = data.get("locations")
    if not isinstance(locations, list):
        raise ValueError("Expected 'locations' to be a list")
    for loc in locations:
        loc_name = loc.get("name")
        if not loc_name:
            continue
        result[date_str][loc_name] = {}
        courts = loc.get("courts")
        if not isinstance(courts, list):
            raise ValueError("Expected 'courts' to be a list")
        for court in courts:
            court_name = court.get("name")
            if court_name and "Tennis Court" in court_name:
                short_name = court_name.replace("Tennis Court ", "Court ")
                result[date_str][loc_name][short_name] = {}
                reservations = court.get("reservations")
                if not isinstance(reservations, list):
                    raise ValueError("Expected 'reservations' to be a list in court")
                for res in reservations:
                    time_slot = res.get("time")
                    booked = res.get("reserved")
                    if time_slot is None or booked is None:
                        raise ValueError("Reservation entry missing 'time' or 'reserved'")
                    result[date_str][loc_name][short_name][time_slot] = booked
    return result

def consolidate_booked_slots(parsed_data: dict) -> dict:
    """
    Consolidates booked slots from parsed reservation data.

    For each date, location, and court, it identifies consecutive booked 30-minute slots,
    merging them into single start/end ISO 8601 time ranges with timezone info.

    Returns:
        A dictionary structured as:
        {
            "Mervin": {
                "Court 1": [("start_iso", "end_iso"), ...],
                "Court 2": [...]
            },
            "Bay": { ... }
        }
    """
    from datetime import datetime, timedelta

    consolidated = {}
    for date_str, locations in parsed_data.items():
        for location, courts in locations.items():
            for court, slots in courts.items():
                # Filter and sort timeslots that are booked
                booked_times = [time_str for time_str, is_booked in slots.items() if is_booked]
                if not booked_times:
                    continue
                booked_times.sort()
                events = []
                fmt = "%Y-%m-%d %H:%M"
                tz = ZoneInfo(TIMEZONE)
                current_start = None
                current_end = None
                for t in booked_times:
                    slot_dt = datetime.strptime(f"{date_str} {t}", fmt)
                    slot_dt = slot_dt.replace(tzinfo=tz)
                    if current_start is None:
                        current_start = slot_dt
                        current_end = slot_dt + timedelta(minutes=30)
                    else:
                        if slot_dt == current_end:
                            current_end += timedelta(minutes=30)
                        else:
                            events.append((current_start.isoformat(), current_end.isoformat()))
                            current_start = slot_dt
                            current_end = slot_dt + timedelta(minutes=30)
                if current_start is not None:
                    events.append((current_start.isoformat(), current_end.isoformat()))
                if location not in consolidated:
                    consolidated[location] = {}
                if court not in consolidated[location]:
                    consolidated[location][court] = []
                consolidated[location][court].extend(events)
    return consolidated

def authenticate_google(credentials_path: str):
    """
    Authenticates to Google Calendar API using a service account credentials file.
    
    Args:
        credentials_path (str): The path to the service account JSON credentials file.
    
    Returns:
        googleapiclient.discovery.Resource: Authorized Google Calendar API service object.
    
    Raises:
        Exception: If credential loading or service creation fails.
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:
        logging.error("Required Google libraries are not installed. Please install 'google-auth' and 'google-api-python-client'.")
        sys.exit(1)
        
    scopes = ['https://www.googleapis.com/auth/calendar.events']
    try:
        credentials = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        service = build('calendar', 'v3', credentials=credentials)
    except Exception as e:
        logging.error(f"Error during Google API authentication: {e}")
        sys.exit(1)
    return service

def Workspace_calendar_events(service, calendar_id: str, time_min_iso: str, time_max_iso: str) -> List[dict]:
    """
    Fetches existing calendar events from a given Google Calendar within the provided time range.
    
    Only returns events that are likely created by this script (filtered by summary starting with "Court ").
    
    Args:
        service: Authorized Google Calendar API service object.
        calendar_id (str): The target calendar ID.
        time_min_iso (str): The lower bound (inclusive) of event start times (ISO format).
        time_max_iso (str): The upper bound (exclusive) of event end times (ISO format).
        
    Returns:
        List[dict]: A list of event dictionaries containing keys 'id', 'summary', 'start', and 'end'.
    """
    events = []
    page_token = None
    while True:
        response = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min_iso,
            timeMax=time_max_iso,
            singleEvents=True,
            orderBy='startTime',
            pageToken=page_token
        ).execute()
        for event in response.get('items', []):
            summary = event.get("summary", "")
            # Filter events: include only those with summary starting with "Court "
            if summary.startswith("Court "):
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))
                events.append({
                    "id": event["id"],
                    "summary": summary,
                    "start": start,
                    "end": end
                })
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return events

def main() -> None:
    parser = argparse.ArgumentParser(description="Hayward Tennis Sync Script")
    parser.add_argument("--dry-run", action="store_true", help="Execute in dry-run mode")
    parser.add_argument("--throttle", type=float, default=DEFAULT_THROTTLE, help="Throttle delay in seconds")
    args: argparse.Namespace = parser.parse_args()
    
    # Set up basic logging to stdout
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Started hayward tennis sync script")
    
    sync_dates = get_sync_date_range()
    logging.info(f"Sync date range: {sync_dates[0]} to {sync_dates[-1]}")
    
    if args.dry_run:
        logging.info("Dry run enabled. No changes will be made.")
    
    # Placeholder for main sync logic
    logging.info("Script execution completed.")

if __name__ == "__main__":
    main()
