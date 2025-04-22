import argparse
import datetime
import logging
import sys
from typing import List, Tuple, Any, Optional
from zoneinfo import ZoneInfo
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError # Import HttpError for better error handling

# Constants (Keep relevant ones)
TIMEZONE: str = 'America/Los_Angeles'
LOCATION_TO_CALENDAR = {
    "Mervin": "c1b24574cbbcfe3d62b323de33ebc50956edf9212737a88f9423c661c5e37204@group.calendar.google.com",
    "Bay": "8320fe0a847ce736584415a3777a3d4eb69e650d459ae9329fa1aaed42cf36d1@group.calendar.google.com"
}

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
    scopes = ['https://www.googleapis.com/auth/calendar.events']
    try:
        credentials = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        service = build('calendar', 'v3', credentials=credentials)
        logging.info("Successfully authenticated with Google Calendar API.")
        return service
    except FileNotFoundError:
        logging.error(f"Credentials file not found at: {credentials_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Failed to authenticate Google service: {e}")
        sys.exit(1)


def Workspace_calendar_events(service: Any, calendar_id: str, time_min_iso: str, time_max_iso: str) -> List[dict]:
    """
    Fetches existing calendar events from a given Google Calendar within the provided time range.

    Only returns events that are likely created by the original script (filtered by summary starting with "Court ").

    Args:
        service: Authorized Google Calendar API service object.
        calendar_id (str): The target calendar ID.
        time_min_iso (str): The lower bound (inclusive) of event start times (ISO format without timezone).
        time_max_iso (str): The upper bound (exclusive) of event end times (ISO format without timezone).

    Returns:
        List[dict]: A list of event dictionaries containing keys 'id', 'summary', 'start', and 'end'. Returns empty list on error.
    """
    events: List[dict] = []
    page_token: Optional[str] = None
    try:
        # Convert local ISO time strings to timezone-aware RFC3339 strings for the API
        tz = ZoneInfo(TIMEZONE)
        # Use T00:00:00 for date-only comparison if time part isn't crucial, or keep time part if needed
        time_min_dt = datetime.datetime.fromisoformat(time_min_iso).replace(tzinfo=tz)
        time_max_dt = datetime.datetime.fromisoformat(time_max_iso).replace(tzinfo=tz)
        time_min_rfc3339 = time_min_dt.isoformat()
        time_max_rfc3339 = time_max_dt.isoformat()

        logging.debug(f"Fetching events for calendar {calendar_id} between {time_min_rfc3339} and {time_max_rfc3339}")

        while True:
            response = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min_rfc3339,
                timeMax=time_max_rfc3339,
                singleEvents=True, # Important for recurring events
                orderBy='startTime',
                pageToken=page_token,
                # Consider adding maxResults if needed, default is 250
                # maxResults=2500 # Max allowed is 2500
            ).execute()

            for event in response.get('items', []):
                summary = event.get("summary", "")
                # Filter events: include only those with summary starting with "Court "
                # Adjust this filter if your original script uses a different naming convention
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
        logging.info(f"Found {len(events)} events matching 'Court *' summary in calendar {calendar_id} within the specified range.")

    except HttpError as e:
        logging.error(f"Error fetching events from calendar {calendar_id}: {e}")
        # Decide if you want to stop or continue with other calendars
        # For now, return empty list for this calendar
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching events for calendar {calendar_id}: {e}")
        # Return empty list

    return events


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
        - If the event is already deleted or not found (e.g., HTTP 404 or 410), logs a warning.
        - For other errors, logs the error but continues execution.
    """
    if dry_run:
        logging.info(f"[Dry-run] Would delete event: {event_id} from calendar {calendar_id}")
        return None
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logging.info(f"Deleted event: {event_id} from calendar {calendar_id}")
    except HttpError as e:
        # 410 Gone (already deleted) or 404 Not Found are common and can be treated as warnings
        if e.resp.status in [404, 410]:
            logging.warning(f"Event {event_id} already deleted or not found (Status: {e.resp.status}): {e}")
        else:
            logging.error(f"Error deleting event {event_id} from calendar {calendar_id}: {e}")
            # Decide if you want to exit: sys.exit(1) or continue
    except Exception as e:
        logging.error(f"An unexpected error occurred while deleting event {event_id}: {e}")
        # Decide if you want to exit: sys.exit(1) or continue
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete Hayward Tennis Sync events from Google Calendar")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without actually deleting events")
    parser.add_argument("--credentials-path", required=True, help="Path to Google service account credentials file")
    parser.add_argument("--days", type=int, default=90, help="Number of days from today to check for events to delete (default: 90)")
    args: argparse.Namespace = parser.parse_args()

    # Set up logging to stdout
    log_level = logging.DEBUG if args.dry_run else logging.INFO # More verbose logging in dry-run
    logging.basicConfig(level=log_level, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info(f"Starting event deletion script. Dry run: {args.dry_run}")

    # Determine credentials path from command-line argument
    credentials_path: str = args.credentials_path
    service = authenticate_google(credentials_path)
    if not service:
        sys.exit(1) # Exit if authentication failed

    # Calculate time boundaries for the deletion window (next N days)
    today = datetime.date.today()
    start_date = today
    end_date = today + datetime.timedelta(days=args.days)

    # Use midnight as the boundary time for simplicity. API uses exclusive end time.
    time_min_iso: str = start_date.strftime("%Y-%m-%d") + "T00:00:00"
    time_max_iso: str = end_date.strftime("%Y-%m-%d") + "T00:00:00"

    logging.info(f"Targeting events from {time_min_iso} up to (but not including) {time_max_iso} [{args.days} days]")

    total_deleted_count = 0
    # Process each location/calendar
    for location, calendar_id in LOCATION_TO_CALENDAR.items():
        logging.info(f"--- Processing calendar for location: {location} ({calendar_id}) ---")

        # Get existing events within the date range that match the script's pattern
        events_to_delete = Workspace_calendar_events(service, calendar_id, time_min_iso, time_max_iso)

        if not events_to_delete:
            logging.info(f"No matching events found to delete for {location}.")
            continue

        logging.info(f"Found {len(events_to_delete)} events to potentially delete for {location}.")

        # Delete each found event
        deleted_count_for_calendar = 0
        for event in events_to_delete:
            delete_google_event(service, calendar_id, event["id"], args.dry_run)
            if not args.dry_run: # Only count if not dry run and deletion didn't raise critical error
                 deleted_count_for_calendar += 1 # Simplistic count, assumes delete worked if no error logged

        logging.info(f"Finished processing for {location}. {'Would have attempted' if args.dry_run else 'Attempted'} deletion of {len(events_to_delete)} events.")
        total_deleted_count += deleted_count_for_calendar if not args.dry_run else len(events_to_delete)


    logging.info("--- Script execution completed. ---")
    if args.dry_run:
        logging.info(f"[Dry-run] Would have attempted to delete {total_deleted_count} events in total.")
    else:
        # Note: This count might be slightly off if specific deletions failed silently (like 404/410)
        logging.info(f"Attempted deletion of approximately {total_deleted_count} events in total.")


if __name__ == "__main__":
    main()