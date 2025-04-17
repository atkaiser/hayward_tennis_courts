import argparse
import datetime
import json
import logging
import os
import sys
import time
import requests
from typing import List, Tuple
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

def diff_events(desired_slots: dict, existing_events: List[dict], location_name: str) -> Tuple[List[dict], List[str]]:
    """
    Compares desired_slots (desired events) with existing_events fetched from the calendar.
    Each desired event is represented as a tuple (court, start_iso, end_iso).
    
    Returns:
        events_to_create: a list of dictionaries with keys 'summary', 'start', 'end'
                          representing new events that need to be created.
        events_to_delete: a list of event IDs from existing_events that are no longer desired.
    """
    desired_tuples = set()
    desired_events = []
    for court, events in desired_slots.items():
        for (start, end) in events:
            event_tuple = (court, start, end)
            desired_tuples.add(event_tuple)
            desired_events.append({"summary": court, "start": start, "end": end})
            
    existing_tuples = set()
    for event in existing_events:
        event_tuple = (event["summary"], event["start"], event["end"])
        existing_tuples.add(event_tuple)
    
    events_to_create = []
    for event in desired_events:
        event_tuple = (event["summary"], event["start"], event["end"])
        if event_tuple not in existing_tuples:
            events_to_create.append(event)
    
    events_to_delete = []
    for event in existing_events:
        event_tuple = (event["summary"], event["start"], event["end"])
        if event_tuple not in desired_tuples:
            events_to_delete.append(event["id"])
    
    logging.info(f"Location {location_name}: {len(events_to_create)} events to create, {len(events_to_delete)} events to delete")
    return events_to_create, events_to_delete

def create_google_event(service, calendar_id: str, court_name: str, start_iso: str, end_iso: str, timezone: str, dry_run: bool) -> dict:
    """
    Creates a Google Calendar event for a given court time slot.
    
    Args:
        service: Authorized Google Calendar API service object.
        calendar_id (str): Target calendar ID.
        court_name (str): Court name (used as event summary).
        start_iso (str): Event start time in ISO 8601 format.
        end_iso (str): Event end time in ISO 8601 format.
        timezone (str): Timezone identifier.
        dry_run (bool): If True, logs action and does not create event.
        
    Returns:
        dict: Details of the created event if not in dry-run mode, otherwise None.
    """
    event_body = {
        "summary": court_name,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone}
    }
    if dry_run:
        logging.info(f"[Dry-run] Would create event: {event_body}")
        return None
    try:
        event = service.events().insert(calendarId=calendar_id, body=event_body).execute()
        logging.info(f"Created event: {event.get('id')}")
        return event
    except Exception as e:
        logging.error(f"Error creating Google Calendar event for {court_name} from {start_iso} to {end_iso}: {e}")
        sys.exit(1)

def delete_google_event(service, calendar_id: str, event_id: str, dry_run: bool) -> None:
    """
    Deletes a Google Calendar event.
    
    Args:
        service: Authorized Google Calendar API service object.
        calendar_id (str): The target calendar ID.
        event_id (str): The ID of the event to delete.
        dry_run (bool): If True, logs the planned deletion without performing it.
        
    Behavior:
        - If dry_run is True, logs the planned deletion and returns None.
        - If dry_run is False, attempts to delete the event using the Calendar API.
        - If the event is already deleted or not found (e.g., HTTP 404), logs a warning.
        - For other errors, logs the error and exits.
    """
    if dry_run:
        logging.info(f"[Dry-run] Would delete event: {event_id} from calendar {calendar_id}")
        return None
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logging.info(f"Deleted event: {event_id} from calendar {calendar_id}")
    except Exception as e:
        if '404' in str(e):
            logging.warning(f"Event {event_id} already deleted or not found: {e}")
        else:
            logging.error(f"Error deleting event {event_id}: {e}")
            sys.exit(1)
    return None

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
