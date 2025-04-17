import argparse
import datetime
import json
import logging
import re
import sys
import time
import requests
from typing import List, Tuple, Any, Optional
from zoneinfo import ZoneInfo
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Constants
TIMEZONE: str = 'America/Los_Angeles'
LOCATION_TO_CALENDAR = {
    "Mervin": "c1b24574cbbcfe3d62b323de33ebc50956edf9212737a88f9423c661c5e37204@group.calendar.google.com",
    "Bay": "8320fe0a847ce736584415a3777a3d4eb69e650d459ae9329fa1aaed42cf36d1@group.calendar.google.com"
}
DEFAULT_THROTTLE: float = 1.5

# Set up session
session: requests.Session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}) # Example User Agent


def get_sync_date_range(num_days: int = 2) -> List[str]:
    """
    Calculates and returns a list of date strings for the sync range.
    Start date is today + 2 days, end date is today + 81 days (80 days total).
    """
    start_date = datetime.date.today() + datetime.timedelta(days=2)
    # Create a list of 80 days starting from start_date
    return [(start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]

def find_csrf_token(html_content: str) -> Optional[str]:
    """
    Parses HTML content to find the CSRF token assigned to window.__csrfToken
    using regular expressions.

    Args:
        html_content: The raw HTML text from the initial page request.

    Returns:
        The extracted CSRF token string, or None if not found.
    """
    # Regex pattern to find: window.__csrfToken = "TOKEN_VALUE";
    # It captures the sequence of characters inside the double quotes.
    # Assumes the token consists of hex characters and hyphens (like a UUID).
    # Escape dots in '__csrfToken' as '.' is a special regex character.
    pattern = r'window\.__csrfToken\s*=\s*"([a-fA-F0-9\-]+)"' # Added \s* for robustness

    match = re.search(pattern, html_content)

    if match:
        token = match.group(1)
        logging.info(f"Successfully extracted CSRF token: {token[:4]}...{token[-4:]}") # Log partial token
        return token
    else:
        logging.warning("Could not find CSRF token pattern (window.__csrfToken = \"...\") in the HTML content.")
        return None

def get_csrf_token() -> Optional[str]:
    initial_url: str = "https://anc.apm.activecommunities.com/haywardrec/reservation/landing/quick?locale=en-US&groupId=2"
    logging.info(f"Making initial request to {initial_url} to establish session...")
    initial_response = session.get(initial_url, timeout=30)
    initial_response.raise_for_status()
    logging.info(f"Initial request successful (Status: {initial_response.status_code}).")
    csrf_token = find_csrf_token(initial_response.text)
    if csrf_token:
        logging.info("Extracted CSRF token.")
    else:
        logging.warning("Could not find CSRF token. Proceeding without it, might fail.")
    return csrf_token

def Workspace_hayward_data(date_str: str, throttle_seconds: float) -> bytes:
    """
    Fetches data from the Hayward API for a given date with throttling.

    Constructs the URL using the provided date_str.
    Implements throttling using time.sleep(throttle_seconds) before making the request.
    
    Returns the raw response content (JSON).
    """
    # Make initial request to get csrf token
    initial_url = "https://anc.apm.activecommunities.com/haywardrec/reservation/landing/quick?locale=en-US&groupId=2"
    logging.info(f"Making initial request to {initial_url} to establish session...")
    initial_response = session.get(initial_url, timeout=30)
    initial_response.raise_for_status()
    logging.info(f"Initial request successful (Status: {initial_response.status_code}).")
    
    # 2. Extract CSRF token (implement find_csrf_token)
    csrf_token = find_csrf_token(initial_response.text)
    if csrf_token:
        logging.info("Extracted CSRF token.")
    else:
        logging.warning("Could not find CSRF token. Proceeding without it, might fail.")
        # Decide if you want to exit here if token is strictly required

    headers = {
        # --- IMPORTANT: Determine the correct header name ---
        'X-Csrf-Token': csrf_token,
        'X-Requested-With': 'XMLHttpRequest', # Sometimes required for AJAX endpoints
        'Referer': 'https://anc.apm.activecommunities.com/haywardrec/reservation/landing/quick?locale=en-US&groupId=2'
    }

    # Construct the URL for the Hayward API endpoint
    url = "https://anc.apm.activecommunities.com/haywardrec/rest/reservation/quickreservation/availability?locale=en-US"
    # Prepare the JSON payload with the required parameters
    payload = {
        "facility_group_id": 2,
        "customer_id": 0,
        "company_id": 0,
        "reserve_date": date_str,
        "start_time": "08:00:00",
        "end_time": "22:00:00",
        "resident": True,
        "reload": False,
        "change_time_range": False
    }
    # Throttle
    time.sleep(throttle_seconds)
    response = session.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response.content

def parse_reservation_data(json_data: bytes, reserve_date: Optional[str] = None) -> dict:
    """
    Parses the raw JSON data from the Hayward API to extract reservation data.

    Supports two formats:
    
    1. New format: The JSON response contains "body" -> "availability" with "time_slots" and "resources".
       Each resource with a "resource_name" containing "Tennis Court" is processed.
       The resource name is expected to be in the format "Location - Tennis Court X".
       Time slot details from "time_slot_details" are matched with "time_slots" to determine reservation status.
       The resulting structure is:
       
       {
           "requested_date": {
               "Location": {
                   "Court X": {"HH:MM": True/False, ...},
                   ...
               },
               ...
           }
       }
    
    Raises:
        ValueError: if the JSON data is invalid or missing required keys.
    """
    data: Any = json.loads(json_data.decode("utf-8"))

    if "body" in data and "availability" in data["body"]:
        avail: dict = data["body"]["availability"]
        time_slots: List[str] = avail.get("time_slots")
        if not isinstance(time_slots, list):
            raise ValueError("Expected 'time_slots' to be a list in availability")
        resources: List[dict] = avail.get("resources")
        if not isinstance(resources, list):
            raise ValueError("Expected 'resources' to be a list in availability")
        # Since the response doesn't include a date, use the provided reserve_date if available.
        if reserve_date is not None:
            date_str: str = reserve_date
        else:
            date_str: str = "requested_date"
        result: dict = {date_str: {}}
        for res in resources:
            resource_name: Optional[str] = res.get("resource_name")
            if resource_name and "Tennis Court" in resource_name:
                parts: List[str] = resource_name.split(" - ")
                if len(parts) != 2:
                    continue
                location: str = parts[0]
                court_full: str = parts[1]
                court_name: str = court_full.replace("Tennis Court ", "Court ")
                if location not in result[date_str]:
                    result[date_str][location] = {}
                details: List[dict] = res.get("time_slot_details")
                if not isinstance(details, list):
                    raise ValueError("Expected 'time_slot_details' to be a list")
                slot_status: dict = {}
                for idx, t in enumerate(time_slots):
                    time_key: str = t[:5]
                    if idx < len(details):
                        detail: dict = details[idx]
                        reserved: bool = (detail.get("status") == 1)
                        slot_status[time_key] = reserved
                    else:
                        slot_status[time_key] = False
                result[date_str][location][court_name] = slot_status
        return result
    else:
        print(data)
        raise ValueError("JSON data missing required 'body' or 'availability' keys")

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
                fmt: str = "%Y-%m-%d %H:%M"
                tz: ZoneInfo = ZoneInfo(TIMEZONE)
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

def authenticate_google(credentials_path: str) -> Any:
    """
    Authenticates to Google Calendar API using a service account credentials file.
    
    Args:
        credentials_path (str): The path to the service account JSON credentials file.
    
    Returns:
        googleapiclient.discovery.Resource: Authorized Google Calendar API service object.
    
    Raises:
        Exception: If credential loading or service creation fails.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    scopes = ['https://www.googleapis.com/auth/calendar.events']
    credentials = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
    service = build('calendar', 'v3', credentials=credentials)
    return service

def Workspace_calendar_events(service: Any, calendar_id: str, time_min_iso: str, time_max_iso: str) -> List[dict]:
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
    events: List[dict] = []
    page_token: Optional[str] = None
    while True:
        from datetime import datetime
        tz = ZoneInfo(TIMEZONE)
        time_min_rfc3339 = datetime.fromisoformat(time_min_iso).replace(tzinfo=tz).isoformat()
        time_max_rfc3339 = datetime.fromisoformat(time_max_iso).replace(tzinfo=tz).isoformat()
        print(time_min_rfc3339)
        print(time_max_rfc3339)
        response = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min_rfc3339,
            timeMax=time_max_rfc3339,
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
    desired_tuples: set = set()
    desired_events: List[dict] = []
    for court, events in desired_slots.items():
        for (start, end) in events:
            event_tuple = (court, start, end)
            desired_tuples.add(event_tuple)
            desired_events.append({"summary": court, "start": start, "end": end})
            
    existing_tuples: set = set()
    for event in existing_events:
        event_tuple = (event["summary"], event["start"], event["end"])
        existing_tuples.add(event_tuple)
    
    events_to_create: List[dict] = []
    for event in desired_events:
        event_tuple = (event["summary"], event["start"], event["end"])
        if event_tuple not in existing_tuples:
            events_to_create.append(event)
    
    events_to_delete: List[str] = []
    for event in existing_events:
        event_tuple = (event["summary"], event["start"], event["end"])
        if event_tuple not in desired_tuples:
            events_to_delete.append(event["id"])
    
    logging.info(f"Location {location_name}: {len(events_to_create)} events to create, {len(events_to_delete)} events to delete")
    return events_to_create, events_to_delete

def create_google_event(service: Any, calendar_id: str, court_name: str, start_iso: str, end_iso: str, timezone: str, dry_run: bool) -> Optional[dict]:
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

def delete_google_event(service: Any, calendar_id: str, event_id: str, dry_run: bool) -> None:
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
    parser.add_argument("--credentials-path", required=True, help="Path to Google service account credentials file")
    args: argparse.Namespace = parser.parse_args()
    
    # Set up logging to stdout
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Started hayward tennis sync script")
    
    # Determine credentials path from command-line argument
    credentials_path: str = args.credentials_path
    service = authenticate_google(credentials_path)
    
    # Determine sync date range
    sync_dates: List[str] = get_sync_date_range()
    logging.info(f"Sync date range: {sync_dates[0]} to {sync_dates[-1]}")
    
    all_parsed_data = {}
    csrf_token: Optional[str] = get_csrf_token()
    # Fetch and parse data for each date
    for date_str in sync_dates:
        logging.info(f"Fetching data for {date_str}...")
        raw_data = Workspace_hayward_data(date_str, args.throttle, csrf_token)
        try:
            daily_data = parse_reservation_data(raw_data, date_str)
        except ValueError as ve:
            logging.error(f"Error parsing data for {date_str}: {ve}")
            sys.exit(1)
        # Merge daily data into all_parsed_data
        all_parsed_data.update(daily_data)
    
    # Get desired state from parsed reservation data by consolidating bookings
    desired_state = consolidate_booked_slots(all_parsed_data)
    
    # Calculate time boundaries for the sync window
    # Use first sync date with time "T00:00:00" and last sync date plus one day "T00:00:00"
    time_min = sync_dates[0] + "T00:00:00"
    last_date = datetime.datetime.strptime(sync_dates[-1], "%Y-%m-%d").date()
    next_day = last_date + datetime.timedelta(days=1)
    time_max = next_day.strftime("%Y-%m-%d") + "T00:00:00"
    
    # Process each location based on the mapping
    for location, calendar_id in LOCATION_TO_CALENDAR.items():
        logging.info(f"Processing location: {location}...")
        if location not in desired_state:
            logging.info(f"No booking data for {location}, skipping.")
            continue
        
        try:
            existing_events = Workspace_calendar_events(service, calendar_id, time_min, time_max)
        except Exception as e:
            logging.warning(f"Failed to fetch events for {location} (calendar {calendar_id}): {e}")
            continue
        
        events_to_create, events_to_delete = diff_events(desired_state[location], existing_events, location)
        logging.info(f"{location}: {len(events_to_create)} events to create, {len(events_to_delete)} events to delete.")
        
        for event in events_to_create:
            create_google_event(service, calendar_id, event["summary"], event["start"], event["end"], TIMEZONE, args.dry_run)
        for event_id in events_to_delete:
            delete_google_event(service, calendar_id, event_id, args.dry_run)
    
    logging.info("Script execution completed.")
        

if __name__ == "__main__":
    main()
