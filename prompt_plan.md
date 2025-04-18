Okay, let's break down the `hayward_tennis_sync.py` project into a detailed blueprint and then generate the iterative prompts for a code-generation LLM.

## Project Blueprint: `hayward_tennis_sync.py`

**Phase 1: Foundation & Setup**

1.  **Basic Script Structure:**
    * Create `hayward_tennis_sync.py`.
    * Add `if __name__ == "__main__":` block.
    * Set up basic logging (to stdout).
    * Define constants: `TIMEZONE = 'America/Los_Angeles'`, `CALENDAR_IDS` (with example IDs), `DEFAULT_THROTTLE = 1.5`.
    * Import necessary standard libraries (`datetime`, `time`, `logging`, `argparse`, `json`, `os`, etc.).
2.  **Argument Parsing:**
    * Implement `argparse` to handle `--dry-run` (boolean flag) and `--throttle` (float, with default).
3.  **Date Range Calculation:**
    * Create a function `get_sync_date_range(num_days=80)` that calculates the start date (today + 2 days) and end date (today + 81 days).
    * Returns a list of date objects or formatted strings required by the Hayward API for the 80 days.

**Phase 2: Hayward Data Handling**

4.  **Hayward API Fetching:**
    * Create a function `Workspace_hayward_data(date_str, throttle_seconds)`:
        * Constructs the correct URL for the given date string. (Requires reverse-engineering the exact URL format needed by the JSON endpoint). Assume for now it takes a simple date parameter.
        * Uses `requests` (or `urllib.request`) to fetch data from the endpoint.
        * Includes error handling for network issues (requests.exceptions.RequestException) - fail immediately.
        * Implements throttling using `time.sleep(throttle_seconds)` *before* making the request.
        * Returns the raw response content (likely JSON, but could be HTML containing JSON or needing parsing). *Initial assumption: It's a direct JSON API.*
5.  **Hayward Data Parsing:**
    * Create a function `parse_reservation_data(json_data)`:
        * Takes the raw JSON data from the fetch step.
        * Navigates the JSON structure to find reservation blocks (e.g., iterating through locations, courts, time slots).
        * Identifies location names (e.g., "Mervin", "Bay").
        * Identifies court names (e.g., "Tennis Court 1", "Tennis Court 2").
        * Filters to *only* include courts containing "Tennis Court".
        * Extracts the time for each slot (e.g., "9:00 AM").
        * Determines if a slot is booked (e.g., based on a `reserved` flag/class or similar indicator in the data).
        * Handles potential parsing errors (e.g., unexpected structure) - raise a clear error.
        * Returns a structured representation, e.g., a dictionary:
            ```python
            {
                "YYYY-MM-DD": {
                    "Mervin": {
                        "Court 1": {"09:00": True, "09:30": True, "10:00": False, ...},
                        "Court 2": {"09:00": False, "09:30": False, ...}
                    },
                    "Bay": { ... }
                }
            }
            ```
            (Key: Date -> Location -> Court -> Time Slot -> Booked Status (True/False))
6.  **Booking Consolidation:**
    * Create a function `consolidate_booked_slots(parsed_data)`:
        * Takes the structured data from the parsing step.
        * Iterates through each date, location, and court.
        * For each court, iterates through the time slots in chronological order.
        * Identifies consecutive *booked* 30-minute slots.
        * Merges consecutive booked slots into single start/end time ranges.
        * Returns a simplified structure representing *only* the desired booked events:
            ```python
            {
                "Mervin": {
                    "Court 1": [("YYYY-MM-DDTHH:MM:SS", "YYYY-MM-DDTHH:MM:SS"), ...], # (start_iso, end_iso)
                    "Court 2": [...]
                },
                "Bay": { ... }
            }
            ```
            (Uses ISO 8601 format strings with timezone info, ready for Google Calendar API).

**Phase 3: Google Calendar Integration**

7.  **Google API Authentication:**
    * Create a function `authenticate_google(credentials_path)`:
        * Uses `google-auth` and `google-api-python-client` libraries.
        * Loads service account credentials from the specified JSON file path.
        * Defines the required scope (`https://www.googleapis.com/auth/calendar.events`).
        * Builds and returns the authorized Google Calendar API service object.
        * Handles credential loading errors - fail immediately.
8.  **Fetch Existing Calendar Events:**
    * Create a function `Workspace_calendar_events(service, calendar_id, time_min_iso, time_max_iso)`:
        * Takes the authenticated service object, a target calendar ID, and the ISO date range.
        * Uses `service.events().list()` to fetch events.
        * Specifies `calendarId`, `timeMin`, `timeMax`, `singleEvents=True`, `orderBy='startTime'`.
        * Handles pagination if many events exist.
        * Parses the response to extract relevant details for comparison (event ID, summary, start time, end time).
        * *Crucially:* Filters events to only include those likely created by this script (e.g., based on the expected title format "Court X"). This avoids deleting manually added events.
        * Returns a list of existing relevant events, perhaps as a list of dictionaries:
            ```python
            [
              {"id": "event_id_1", "summary": "Court 1", "start": "YYYY-MM-DDTHH:MM:SSZ", "end": "YYYY-MM-DDTHH:MM:SSZ"},
              ...
            ]
            ```
9.  **Event Comparison (Diffing):**
    * Create a function `diff_events(desired_slots, existing_events, location_name)`:
        * `desired_slots`: The output from `consolidate_booked_slots` for a *specific location*.
        * `existing_events`: The output from `Workspace_calendar_events` for that location's calendar.
        * `location_name`: Used for logging.
        * Compares the desired state (court, start, end) with the existing state.
        * Needs a consistent way to represent events for comparison (e.g., tuple `(court_name, start_iso, end_iso)`).
        * Generates two lists:
            * `events_to_create`: List of desired slots (formatted for `create_google_event`) that don't have a matching existing event.
            * `events_to_delete`: List of existing event IDs whose corresponding slot is no longer desired.
        * Returns `(events_to_create, events_to_delete)`.
10. **Create Google Calendar Event:**
    * Create a function `create_google_event(service, calendar_id, court_name, start_iso, end_iso, timezone, dry_run)`:
        * Takes service, calendar ID, event details, timezone, and dry-run flag.
        * Constructs the event body dictionary according to Google Calendar API specs (summary=court\_name, start={'dateTime': start\_iso, 'timeZone': timezone}, end={'dateTime': end\_iso, 'timeZone': timezone}).
        * If `dry_run` is True, logs the planned creation and returns `None`.
        * If `dry_run` is False, calls `service.events().insert(calendarId=calendar_id, body=event_body).execute()`.
        * Logs the action (creation attempt or dry-run log).
        * Includes error handling for Google API errors - fail immediately.
        * Returns the created event details (or `None` on dry run).
11. **Delete Google Calendar Event:**
    * Create a function `delete_google_event(service, calendar_id, event_id, dry_run)`:
        * Takes service, calendar ID, event ID to delete, and dry-run flag.
        * If `dry_run` is True, logs the planned deletion and returns `None`.
        * If `dry_run` is False, calls `service.events().delete(calendarId=calendar_id, eventId=event_id).execute()`.
        * Logs the action (deletion attempt or dry-run log).
        * Includes error handling for Google API errors (e.g., event already deleted) - log warning but continue if possible, fail on others.

**Phase 4: Orchestration & Execution**

12. **Main Function Logic:**
    * Implement the `main()` function:
        * Parse command-line arguments.
        * Set up logging verbosely.
        * Determine the Google credentials path (e.g., from env var `GOOGLE_APPLICATION_CREDENTIALS` or a hardcoded fallback).
        * Call `authenticate_google`.
        * Call `get_sync_date_range`.
        * Initialize an empty dictionary `all_parsed_data`.
        * Loop through each date in the range:
            * Log progress (e.g., "Fetching data for YYYY-MM-DD...").
            * Call `Workspace_hayward_data` (with throttle).
            * Call `parse_reservation_data`. Handle potential parsing errors for a single day (log error, maybe continue to next day or fail depending on strictness required - spec says fail immediately on API/network errors, let's extend that to critical parsing errors).
            * Merge the day's parsed data into `all_parsed_data`.
        * Call `consolidate_booked_slots` on `all_parsed_data` to get the final `desired_state`.
        * Loop through the locations defined in `CALENDAR_IDS`:
            * Log progress (e.g., "Processing location: Mervin...").
            * Get the `calendar_id` for the current location. If not found in `desired_state` (e.g., no courts parsed), skip silently. If not found in `CALENDAR_IDS`, log warning and skip.
            * Calculate `time_min_iso` and `time_max_iso` covering the *entire* 80-day sync window.
            * Call `Workspace_calendar_events` for the location's calendar ID and date range. Handle errors (log warning and skip location if calendar is inaccessible).
            * Call `diff_events` using the `desired_state` for the current location and the `existing_events`.
            * Log the number of events to create/delete.
            * Loop through `events_to_create`: Call `create_google_event` (pass `dry_run` flag).
            * Loop through `events_to_delete`: Call `delete_google_event` (pass `dry_run` flag).
        * Log completion message.
        * Implement `try...except` around the main logic to catch critical errors, log them, and exit with a non-zero status code.

**Phase 5: Testing**

13. **Unit Tests (`pytest`):**
    * Create test functions for:
        * `test_get_sync_date_range`: Verify correct dates.
        * `test_fetch_hayward_data`: Mock `requests.get`, test URL construction, throttle call (`time.sleep`), error handling.
        * `test_parse_reservation_data`: Use sample JSON, test extraction, filtering, booked status detection, error handling.
        * `test_consolidate_booked_slots`: Test various booking patterns (adjacent, non-adjacent, empty). Verify ISO format output.
        * `test_authenticate_google`: Mock Google auth libraries, verify scope and credential loading.
        * `test_fetch_calendar_events`: Mock `service.events().list().execute()`, test parameter usage, pagination mocking, filtering logic.
        * `test_diff_events`: Provide various desired/existing states, verify correct `to_create`/`to_delete` lists.
        * `test_create_google_event`: Mock `service.events().insert().execute()`, test event body structure, dry-run logic.
        * `test_delete_google_event`: Mock `service.events().delete().execute()`, test parameter usage, dry-run logic.
    * Use `pytest` fixtures and mocking libraries (`unittest.mock`).

---

## Iterative Prompts for Code Generation LLM

Here are the prompts designed to build the script incrementally, focusing on TDD. Each prompt assumes the LLM has access to the code generated in the previous steps.

---

**Prompt 1: Basic Structure, Constants, Argument Parsing, and Logging**

```text
Generate the initial structure for a Python script named `hayward_tennis_sync.py`.

**Requirements:**
1.  Include standard library imports: `logging`, `argparse`, `datetime`, `time`, `os`, `json`.
2.  Set up basic logging to standard output (INFO level). Include a timestamp and log level in the format.
3.  Define the following constants at the top level:
    * `TIMEZONE = 'America/Los_Angeles'`
    * `CALENDAR_IDS = {"Mervin": "mervin_calendar_id@example.com", "Bay": "bay_calendar_id@example.com"}` (Use placeholder IDs)
    * `DEFAULT_THROTTLE = 1.5` (seconds)
4.  Implement argument parsing using `argparse`:
    * Add a `--dry-run` argument (action='store_true', help message explaining it prevents actual changes).
    * Add a `--throttle` argument (type=float, default=`DEFAULT_THROTTLE`, help message explaining it sets sleep time between Hayward API requests).
5.  Create a basic `main()` function that:
    * Parses the arguments.
    * Logs the starting message with script name.
    * Logs the parsed arguments (e.g., "Dry run mode: True/False", "Throttle set to: X.Y seconds").
    * Logs a completion message.
6.  Include the standard `if __name__ == "__main__":` block to call `main()`.
7.  Add basic docstrings for the script and the `main` function.
8.  **Generate `pytest` unit tests** for the argument parsing logic:
    * Test default values are set correctly when no arguments are provided.
    * Test that `--dry-run` correctly sets the flag.
    * Test that `--throttle` correctly sets the float value.
    * Test providing both arguments.
```

---

**Prompt 2: Date Range Calculation**

```text
Building on the previous `hayward_tennis_sync.py` script:

1.  **Define a function `get_sync_date_range(num_days: int = 80) -> list[datetime.date]`:**
    * This function should calculate the date range for syncing.
    * The range starts **two days** from the current date (`today + 2 days`).
    * The range includes `num_days` total days (so it ends `today + 2 + num_days - 1` days from now).
    * It should return a list of `datetime.date` objects representing each day in the range.
    * Use `datetime.date.today()` to get the current date.
    * Include error handling for `num_days` being non-positive (e.g., raise ValueError).
    * Add clear docstrings and type hints.
2.  **Modify the `main` function:**
    * Call `get_sync_date_range()` after parsing arguments.
    * Log the calculated start and end dates of the range.
3.  **Generate `pytest` unit tests** for `get_sync_date_range`:
    * Use `unittest.mock.patch` to mock `datetime.date.today()` to return a fixed date for predictable results.
    * Test the default `num_days=80`. Verify the start date is today+2 days. Verify the end date is today+81 days. Verify the list contains exactly 80 dates.
    * Test with a different `num_days` value (e.g., 5).
    * Test that it raises `ValueError` for `num_days=0` or `num_days=-1`.
```

---

**Prompt 3: Hayward API Fetch Function (Mocked)**

```text
Continuing with `hayward_tennis_sync.py`:

1.  **Import the `requests` library.** Add it to the project requirements (e.g., a `requirements.txt` file or mention it).
2.  **Define a function `Workspace_hayward_data(target_date: datetime.date, throttle_seconds: float) -> dict`:**
    * **Goal:** Fetch reservation data for a *single* specified date from the Hayward Rec JSON endpoint.
    * **URL Construction:** Determine the *exact* URL format needed. The spec mentions it's reverse-engineered from the dropdown. **For now, assume the URL is `https://anc.apm.activecommunities.com/haywardrec/rest/calendars/facilities/2/daterange/{YYYYMMDD}/{YYYYMMDD}?locale=en-US` where {YYYYMMDD} is the `target_date` formatted.** Add a constant `HAYWARD_API_ENDPOINT_TEMPLATE` for this URL structure. Use f-string formatting with `target_date.strftime('%Y%m%d')`.
    * **Throttling:** Call `time.sleep(throttle_seconds)` *before* making the request. Log that throttling is occurring.
    * **Request:** Use `requests.get()` to fetch the data. Set a reasonable timeout (e.g., 30 seconds). Include standard headers like `User-Agent`.
    * **Error Handling:**
        * Use a `try...except requests.exceptions.RequestException as e:` block. Inside the except block, log the error clearly (including the URL and the exception details) and re-raise a custom exception (e.g., `HaywardFetchError(Exception)`) or simply re-raise the original exception to halt the script as per the spec (fail immediately).
        * Check the response status code using `response.raise_for_status()`. This will raise an `HTTPError` for bad responses (4xx or 5xx). Catch this within the same block or let it propagate.
    * **Return Value:** If successful, parse the response body as JSON using `response.json()` and return the resulting dictionary.
    * Add clear docstrings and type hints.
3.  **Modify the `main` function:**
    * Inside a placeholder loop (e.g., `for sync_date in date_range[:1]: # Process only first day for now`), call `Workspace_hayward_data` with the date and the parsed `throttle` argument.
    * Log the fetched data (or a summary) for now. Wrap this call in a `try...except` block that catches the potential fetch error and logs a fatal error message before exiting (`sys.exit(1)` - import `sys`).
4.  **Generate `pytest` unit tests** for `Workspace_hayward_data`:
    * Use `unittest.mock.patch` to mock `requests.get`.
    * Test successful fetch: Mock `requests.get` to return a mock response object with `status_code=200` and a `.json()` method returning sample JSON data (`{'status': 'success'}`). Verify the correct URL was called. Verify the returned data matches the sample JSON.
    * Test throttling: Use `unittest.mock.patch` to mock `time.sleep`. Verify it's called with the correct `throttle_seconds`.
    * Test network error: Mock `requests.get` to raise `requests.exceptions.ConnectionError`. Verify that the function raises the expected exception (e.g., `HaywardFetchError` or `requests.exceptions.ConnectionError`).
    * Test HTTP error: Mock `requests.get` to return a mock response with `status_code=404` and configure `raise_for_status` on the mock to raise `requests.exceptions.HTTPError`. Verify the function raises the expected exception.
    * Test correct URL formatting based on the input date.
```

*(Self-correction: Need to define the custom exception `HaywardFetchError` or decide to re-raise directly. Let's stick to re-raising the original `requests` exception for simplicity and immediate failure as per spec).*

---

**Prompt 4: Hayward Data Parsing Function**

```text
Building on the previous steps for `hayward_tennis_sync.py`:

1.  **Define a function `parse_reservation_data(api_response: dict, target_date: datetime.date) -> dict`:**
    * **Goal:** Parse the JSON dictionary returned by `Workspace_hayward_data` for a single day and extract booked tennis court slots.
    * **Input:** The JSON dictionary (`api_response`) and the `target_date` (needed for the output structure key).
    * **Parsing Logic (Based on hypothetical JSON structure - adjust if real structure is known):**
        * Assume `api_response` has a structure like `{'calendar': {'resourceCalendar': [...]}}`.
        * Iterate through the list in `resourceCalendar`. Each item might represent a facility/location (e.g., "Mervin", "Bay"). Extract the location name.
        * Inside each location, assume there's a list of resources/courts (e.g., "Tennis Court 1", "Fitness Room"). Extract the resource name.
        * **Filter:** Only process resources whose name *contains* the string `"Tennis Court"`. Ignore others silently.
        * Inside each relevant court, assume there's a list of time slots (e.g., `{'startTime': '09:00 AM', 'status': 'Reserved'}` or similar). Extract the time (e.g., "09:00 AM") and booked status (True if 'Reserved' or similar, False otherwise). Handle potential variations in status indicators. Convert time strings (like "09:00 AM") to a consistent format, perhaps 24-hour HH:MM (e.g., "09:00", "15:30").
    * **Error Handling:** If the JSON structure is missing expected keys (e.g., `KeyError`, `IndexError`, `TypeError`), log a descriptive error message and raise a custom exception (e.g., `HaywardParseError(Exception)`) to halt the script.
    * **Output Structure:** Return a dictionary representing the parsed data for *this specific day*:
        ```python
        {
            "YYYY-MM-DD": { # Key is target_date formatted as string
                "Mervin": {
                    "Court 1": {"09:00": True, "09:30": True, "10:00": False, ...}, # Key: HH:MM, Value: booked_status
                    "Court 2": {"09:00": False, ...}
                },
                "Bay": { # Include Bay only if tennis courts found there
                   "Court 1": { ... }
                }
            }
        }
        ```
        * Use the `target_date.strftime('%Y-%m-%d')` for the top-level key.
        * Extract the simple court name (e.g., "Court 1") from the full resource name (e.g., "Mervin - Tennis Court 1"). Be robust to variations.
    * Add clear docstrings and type hints. Define the `HaywardParseError` exception class.
2.  **Modify the `main` function:**
    * In the loop processing each date, after successfully calling `Workspace_hayward_data`, call `parse_reservation_data` with the result and the current `sync_date`.
    * Store the result. For now, just log a summary of the parsed data structure (e.g., number of locations/courts found).
    * Update the `try...except` block around the fetch/parse calls to also catch `HaywardParseError`. Log the error and exit (`sys.exit(1)`).
3.  **Generate `pytest` unit tests** for `parse_reservation_data`:
    * Define sample `api_response` JSON dictionaries (as Python dicts) covering various scenarios:
        * Normal case with multiple locations, tennis courts, non-tennis courts, booked and available slots.
        * Case with only one location or one court.
        * Case with no tennis courts at a location.
        * Case with no booked slots.
        * Case with unexpected structure (to test error handling).
    * For each scenario, assert that the output dictionary matches the expected structure and data.
    * Verify that non-"Tennis Court" resources are ignored.
    * Verify correct extraction of location and simplified court names.
    * Verify correct time formatting (HH:MM) and booked status (True/False).
    * Use `pytest.raises` to test that `HaywardParseError` is raised for malformed input.
```

*(Self-correction: Need a robust way to get "Court X" from "Location - Tennis Court X". String splitting or regex might be needed. Let's specify using simple string manipulation first, assuming a consistent pattern like " - ").*

---

**Prompt 5: Booking Consolidation Function**

```text
Continuing with `hayward_tennis_sync.py`:

1.  **Import `pytz` library.** Add it to requirements.
2.  **Define a function `consolidate_booked_slots(all_parsed_data: dict, timezone_str: str) -> dict`:**
    * **Goal:** Take the aggregated parsed data (from multiple days) and merge consecutive 30-minute booked slots into single event time ranges using timezone-aware ISO 8601 format.
    * **Input:** `all_parsed_data` (a dictionary merging the outputs from `parse_reservation_data` across all fetched days, structure: `{'YYYY-MM-DD': {'Location': {'Court': {'HH:MM': bool}}}}`) and the `timezone_str` (e.g., 'America/Los_Angeles').
    * **Logic:**
        * Initialize an empty `consolidated_data` dictionary.
        * Get the `pytz` timezone object from `timezone_str`.
        * Iterate through dates (`YYYY-MM-DD`), locations, and courts in `all_parsed_data`.
        * For each court on each day:
            * Get the time slots dictionary (`{'HH:MM': booked_status}`).
            * Sort the time slots chronologically (e.g., `sorted(slots.items())`).
            * Iterate through the sorted slots:
                * If a slot is booked (`status == True`):
                    * Check if it continues a previously started block.
                    * If it's the start of a new block, record the start time.
                    * Keep track of the end time of the current block.
                * If a slot is *not* booked, or it's the last slot:
                    * If a block was in progress, finalize it. Convert the recorded start time string ("HH:MM") and the *end* time of the *last booked slot* in the block (e.g., if 9:00 and 9:30 are booked, the block is 9:00-10:00) into timezone-aware `datetime` objects. Use the date string (`YYYY-MM-DD`) and the time string. Remember that a 30-min slot starting at `HH:MM` *ends* at `HH:MM` + 30 minutes.
                    * Format the start and end datetimes into ISO 8601 strings including timezone offset (e.g., `dt.isoformat()`).
                    * Append the `(start_iso, end_iso)` tuple to a list for the current `location -> court`. Initialize lists/dicts in `consolidated_data` as needed.
    * **Output Structure:** Return the `consolidated_data` dictionary:
        ```python
        {
            "Mervin": {
                "Court 1": [("YYYY-MM-DDTHH:MM:SS-HH:MM", "YYYY-MM-DDTHH:MM:SS-HH:MM"), ...], # (start_iso, end_iso) tuples
                "Court 2": [...]
            },
            "Bay": { ... }
        }
        ```
        * Keys are Location -> Court Name -> List of ISO 8601 start/end tuples.
    * Add clear docstrings and type hints. Handle potential errors during datetime parsing/conversion.
3.  **Modify the `main` function:**
    * After the loop fetching/parsing all dates, aggregate the daily parsed results into a single `all_parsed_data` dictionary.
    * Call `consolidate_booked_slots` with `all_parsed_data` and the `TIMEZONE` constant.
    * Store the result in `desired_state`.
    * Log a summary of the consolidated state (e.g., total number of booked slots found across all locations/courts).
4.  **Generate `pytest` unit tests** for `consolidate_booked_slots`:
    * Create sample `all_parsed_data` inputs covering:
        * Single booked slot.
        * Multiple consecutive booked slots (e.g., 9:00, 9:30 -> one event 9:00-10:00).
        * Multiple non-consecutive booked slots (e.g., 9:00, 10:30 -> two events).
        * Slots spanning across noon or other tricky times.
        * Multiple courts/locations/dates.
        * A court with no booked slots.
        * A day with no booked slots.
    * Assert that the output dictionary structure is correct.
    * Verify the start and end times in the ISO strings are accurate, timezone-aware, and reflect the 30-minute increment logic (end time is start time + 30 mins * number of consecutive slots). Use `datetime.fromisoformat` to parse the output strings and check their values and timezone info.
```

---

**Prompt 6: Google API Authentication Function**

```text
Now let's add Google Calendar API integration to `hayward_tennis_sync.py`.

1.  **Install Google Client Libraries:** Add `google-api-python-client` and `google-auth-httplib2` and `google-auth-oauthlib` to requirements. Import necessary components (`google.oauth2.service_account`, `googleapiclient.discovery`, `google.auth.exceptions`).
2.  **Define a function `authenticate_google(credentials_path: str) -> googleapiclient.discovery.Resource`:**
    * **Goal:** Authenticate using Google Service Account credentials and build the Calendar API service object.
    * **Input:** `credentials_path` (string path to the service account JSON file).
    * **Logic:**
        * Define the required scope: `SCOPES = ['https://www.googleapis.com/auth/calendar.events']`.
        * Use `google.oauth2.service_account.Credentials.from_service_account_file()` to load credentials, specifying the path and scopes.
        * Use `googleapiclient.discovery.build()` to build the 'calendar' service, version 'v3', using the loaded credentials.
        * Return the built service object.
    * **Error Handling:** Wrap credential loading and service building in a `try...except google.auth.exceptions.GoogleAuthError as e:` block (or more specific exceptions like `FileNotFoundError`). Log a clear error message and re-raise a custom exception `GoogleAuthError(Exception)` or the original exception to halt the script.
    * Add clear docstrings and type hints. Define `GoogleAuthError` exception class.
3.  **Modify the `main` function:**
    * Determine the credentials path. **Priority:** Check environment variable `GOOGLE_APPLICATION_CREDENTIALS`. If not set, fall back to a hardcoded path (e.g., `./credentials.json`) or make it a required command-line argument. Log which path is being used. Add this check near the beginning.
    * Call `authenticate_google` with the determined path *before* interacting with Google Calendar (e.g., before fetching existing events). Store the returned `service` object.
    * Wrap the call in a `try...except GoogleAuthError` block. Log fatal error and exit if authentication fails.
4.  **Generate `pytest` unit tests** for `authenticate_google`:
    * Use `unittest.mock.patch` extensively to mock:
        * `google.oauth2.service_account.Credentials.from_service_account_file`
        * `googleapiclient.discovery.build`
    * Test successful authentication: Verify `from_service_account_file` is called with the correct path and scopes. Verify `build` is called with 'calendar', 'v3', and the mocked credentials. Assert the function returns the mocked service object.
    * Test credential loading failure: Mock `from_service_account_file` to raise `FileNotFoundError` or `google.auth.exceptions.DefaultCredentialsError`. Assert that the function raises the expected exception (`GoogleAuthError` or the original).
    * Test service build failure: Mock `build` to raise an exception. Assert that the function raises the expected exception.
```

*(Self-correction: Need to decide on credential path strategy. Env var `GOOGLE_APPLICATION_CREDENTIALS` is standard; let's prioritize that and add a check/log message.)*

---

**Prompt 7: Fetch Existing Google Calendar Events Function**

```text
Continuing with Google Calendar integration in `hayward_tennis_sync.py`:

1.  **Define a function `Workspace_calendar_events(service: googleapiclient.discovery.Resource, calendar_id: str, time_min_iso: str, time_max_iso: str) -> list[dict]`:**
    * **Goal:** Fetch existing events from a *specific* Google Calendar within a given time range that were likely created by this script.
    * **Inputs:** Authenticated `service` object, `calendar_id`, and the overall sync window start (`time_min_iso`) and end (`time_max_iso`) as ISO 8601 strings.
    * **Logic:**
        * Use `service.events().list()` method.
        * Provide parameters: `calendarId=calendar_id`, `timeMin=time_min_iso`, `timeMax=time_max_iso`, `singleEvents=True`, `orderBy='startTime'`. Optionally set `maxResults` (e.g., 250) and handle pagination if needed (check for `nextPageToken` in response and loop).
        * **Filtering:** Iterate through the fetched events (`items` in the response). Only keep events whose `summary` matches the expected pattern, e.g., starting with `"Court "` followed by a number (`"Court \\d+"`). Use regex (`import re`) for robust matching.
        * **Data Extraction:** For each *matching* event, extract its `id`, `summary`, `start.dateTime`, and `end.dateTime`.
    * **Output:** Return a list of dictionaries, each representing a relevant existing event: `[{'id': '...', 'summary': 'Court 1', 'start': 'ISO_DATETIME', 'end': 'ISO_DATETIME'}, ...]`. Return an empty list if no matching events are found or the calendar is empty.
    * **Error Handling:** Wrap the `service.events().list().execute()` call in a `try...except googleapiclient.errors.HttpError as e:` block. Log specific errors (e.g., 404 Not Found if `calendar_id` is invalid/inaccessible). If the error indicates the calendar is inaccessible (e.g., 404), log a warning, and return an empty list (allowing the script to skip this location). For other API errors, log and re-raise to halt the script.
    * Add clear docstrings and type hints.
2.  **Modify the `main` function:**
    * Inside the loop iterating through `CALENDAR_IDS.items()`:
        * Get the `location_name` and `calendar_id`.
        * Check if `location_name` exists as a key in the `desired_state` dictionary. If not, log a debug message ("No desired bookings found for location X, skipping calendar fetch.") and `continue` to the next location.
        * Determine the overall `time_min_iso` and `time_max_iso` for the *entire 80-day sync window*. Get the first date from `date_range` and the last date, create `datetime` objects at the beginning/end of those days respectively, make them timezone-aware using `pytz`, and format as ISO strings.
        * Call `Workspace_calendar_events` with the `service`, `calendar_id`, and the calculated `time_min_iso`, `time_max_iso`.
        * Store the result in `existing_events`. Handle the case where it returns an empty list due to calendar access issues (the function should log this).
        * Log the number of existing relevant events found for the location.
3.  **Generate `pytest` unit tests** for `Workspace_calendar_events`:
    * Mock the `service.events().list().execute()` method.
    * Test fetching with matching events: Mock the return value to include events matching the "Court X" summary pattern and some non-matching ones. Verify only matching events are returned in the correct format.
    * Test fetching with no matching events: Mock the return value with events having different summaries. Verify an empty list is returned.
    * Test fetching from an empty calendar: Mock the return value with an empty `items` list. Verify an empty list is returned.
    * Test pagination: Mock `execute()` to return a `nextPageToken` first, then the rest of the items on the second call. Verify `list()` is called twice with the correct `pageToken`.
    * Test API Error (404 Not Found): Mock `execute()` to raise `googleapiclient.errors.HttpError` with a mock response status of 404. Verify a warning is logged and an empty list is returned.
    * Test other API Error (e.g., 500): Mock `execute()` to raise `HttpError` with status 500. Verify the error is logged and the exception is re-raised.
    * Verify correct parameters (`calendarId`, `timeMin`, `timeMax`, etc.) are passed to `service.events().list()`.
```

---

**Prompt 8: Event Diffing Function**

```text
Let's implement the core comparison logic in `hayward_tennis_sync.py`.

1.  **Define a function `diff_events(desired_slots: dict, existing_events: list[dict], location_name: str, timezone_str: str) -> tuple[list[dict], list[str]]`:**
    * **Goal:** Compare the desired state of bookings (from `consolidate_booked_slots`) with the actual events currently in Google Calendar (from `Workspace_calendar_events`) and determine what needs to be created or deleted.
    * **Inputs:**
        * `desired_slots`: The dictionary for a *single location* from `consolidate_booked_slots` (`{'Court Name': [(start_iso, end_iso), ...]}`).
        * `existing_events`: The list of dictionaries from `Workspace_calendar_events` for that location (`[{'id': ..., 'summary': ..., 'start': ..., 'end': ...}]`).
        * `location_name`: For logging purposes.
        * `timezone_str`: Needed to parse ISO strings robustly if they lack explicit offsets (though Google's should have them).
    * **Logic:**
        * **Normalization:** Create sets for efficient comparison.
            * Create a set `desired_set` containing tuples representing each desired event: `{(court_name, start_iso, end_iso), ...}`. Iterate through `desired_slots` to build this.
            * Create a set `existing_set` containing tuples representing each existing event: `{(court_name, start_iso, end_iso), ...}`. Iterate through `existing_events`. Note: Google API might return ISO strings with 'Z' (UTC). Ensure comparison is robust, potentially by converting both desired and existing datetimes to the *same timezone* (e.g., UTC or the script's local `TIMEZONE`) before creating the tuples, or by carefully parsing ISO strings. Using `datetime.fromisoformat` and comparing the resulting `datetime` objects is safest. Store a mapping from the `(court, start, end)` tuple back to the `event_id` for deletion purposes (e.g., `existing_event_map = {(court, start, end): event_id}`).
        * **Comparison:**
            * `events_to_create_tuples = desired_set - existing_set`
            * `events_to_delete_tuples = existing_set - desired_set`
        * **Format Output:**
            * `events_to_create`: Convert tuples from `events_to_create_tuples` into dictionaries suitable for the `create_google_event` function (e.g., `{'court_name': 'Court 1', 'start_iso': ..., 'end_iso': ...}`).
            * `event_ids_to_delete`: Use the `existing_event_map` to look up the Google Calendar event IDs corresponding to the tuples in `events_to_delete_tuples`. Collect these IDs into a list of strings.
    * **Output:** Return the tuple `(events_to_create, event_ids_to_delete)`.
    * Add clear docstrings and type hints. Be careful with datetime comparisons across potential timezone representations (e.g., Z vs -07:00). Using timezone-aware datetime objects for comparison is recommended.
2.  **Modify the `main` function:**
    * Inside the location loop, after fetching `existing_events`:
        * Get the `desired_slots_for_location` from the main `desired_state` dictionary (handle `KeyError` if the location somehow isn't in `desired_state`, though earlier checks should prevent this). Default to an empty dict if needed.
        * Call `diff_events` with `desired_slots_for_location`, `existing_events`, `location_name`, and `TIMEZONE`.
        * Store the results in `events_to_create` and `event_ids_to_delete`.
        * Log the number of events identified for creation and deletion for this location.
3.  **Generate `pytest` unit tests** for `diff_events`:
    * Define sample `desired_slots` and `existing_events` inputs. Use realistic ISO 8601 strings, potentially with different timezone offsets ('Z' vs '-07:00') to test robustness.
    * Test scenarios:
        * No changes needed (desired == existing).
        * Only new events to create (existing is empty or a subset).
        * Only existing events to delete (desired is empty or a subset).
        * Mix of creates and deletes.
        * Events with identical times but different court names.
    * Assert that the returned `events_to_create` list contains the correct dictionaries.
    * Assert that the returned `event_ids_to_delete` list contains the correct event IDs.
    * Test edge case with empty `desired_slots` or empty `existing_events`.
    * Ensure the comparison correctly handles timezone differences in ISO strings if applicable (e.g., by converting to a common timezone like UTC before comparison).
```

---

**Prompt 9: Create and Delete Google Calendar Event Functions**

```text
Almost there! Let's add the functions to actually modify the Google Calendar in `hayward_tennis_sync.py`.

1.  **Define function `create_google_event(service: ..., calendar_id: str, event_details: dict, timezone: str, dry_run: bool) -> dict | None`:**
    * **Goal:** Create a single event in Google Calendar.
    * **Inputs:** Authenticated `service`, `calendar_id`, `event_details` (dict like `{'court_name': ..., 'start_iso': ..., 'end_iso': ...}` from `diff_events`), `timezone` string, `dry_run` flag.
    * **Logic:**
        * Construct the event body dictionary for the Google Calendar API:
            ```python
            event_body = {
                'summary': event_details['court_name'],
                'start': {'dateTime': event_details['start_iso'], 'timeZone': timezone},
                'end': {'dateTime': event_details['end_iso'], 'timeZone': timezone},
                # Optional: Add a description or extended property to mark script-generated events
                # 'description': 'Automatically synced by hayward_tennis_sync.py'
            }
            ```
        * Log the intention: "Planning to create event: [Summary] [Start Time] on calendar [Calendar ID]".
        * If `dry_run` is True, log "[Dry Run] Skipping actual event creation." and return `None`.
        * If `dry_run` is False:
            * Call `service.events().insert(calendarId=calendar_id, body=event_body).execute()`.
            * Log success: "Successfully created event [Event ID]: [Summary]".
            * Return the created event resource (the result of `execute()`).
    * **Error Handling:** Wrap the `execute()` call in `try...except googleapiclient.errors.HttpError as e:`. Log the specific error details (API error code, message) and re-raise to halt the script on failure.
    * Add clear docstrings and type hints.
2.  **Define function `delete_google_event(service: ..., calendar_id: str, event_id: str, dry_run: bool) -> None`:**
    * **Goal:** Delete a single event from Google Calendar.
    * **Inputs:** Authenticated `service`, `calendar_id`, `event_id` string, `dry_run` flag.
    * **Logic:**
        * Log the intention: "Planning to delete event ID: [Event ID] from calendar [Calendar ID]".
        * If `dry_run` is True, log "[Dry Run] Skipping actual event deletion." and return.
        * If `dry_run` is False:
            * Call `service.events().delete(calendarId=calendar_id, eventId=event_id).execute()`. Note: Successful deletion returns an empty response, so no need to store result unless checking for specific status codes if needed.
            * Log success: "Successfully deleted event ID: [Event ID]".
    * **Error Handling:** Wrap the `execute()` call in `try...except googleapiclient.errors.HttpError as e:`.
        * If the error status is 404 or 410 (Not Found / Gone - event already deleted), log a *warning* ("Event ID [Event ID] already deleted, skipping.") and *return* (do not fail the script).
        * For any other `HttpError`, log the error details and re-raise to halt the script.
    * Add clear docstrings and type hints.
3.  **Modify the `main` function:**
    * Inside the location loop, after calling `diff_events`:
        * Loop through the `events_to_create` list. For each item, call `create_google_event`, passing the `service`, `calendar_id`, the event details dict, `TIMEZONE`, and the parsed `args.dry_run`.
        * Loop through the `event_ids_to_delete` list. For each `event_id`, call `delete_google_event`, passing the `service`, `calendar_id`, `event_id`, and `args.dry_run`.
4.  **Generate `pytest` unit tests** for `create_google_event` and `delete_google_event`:
    * Mock `service.events().insert().execute()` and `service.events().delete().execute()`.
    * **Create Tests:**
        * Test successful creation (`dry_run=False`): Verify `insert().execute()` is called with the correct `calendarId` and a properly structured `event_body`. Verify logs.
        * Test dry-run creation (`dry_run=True`): Verify `insert().execute()` is *not* called. Verify dry-run log message.
        * Test creation API error (`dry_run=False`): Mock `execute()` to raise `HttpError`. Verify error is logged and exception is re-raised.
    * **Delete Tests:**
        * Test successful deletion (`dry_run=False`): Verify `delete().execute()` is called with the correct `calendarId` and `eventId`. Verify logs.
        * Test dry-run deletion (`dry_run=True`): Verify `delete().execute()` is *not* called. Verify dry-run log message.
        * Test deletion API error (404/410 Gone) (`dry_run=False`): Mock `execute()` to raise `HttpError` with status 404/410. Verify warning is logged and *no exception* is raised.
        * Test other deletion API error (`dry_run=False`): Mock `execute()` to raise `HttpError` with status 500. Verify error is logged and exception is re-raised.
```

---

**Prompt 10: Final Orchestration and Error Handling in Main**

```text
This is the final step to tie everything together in `hayward_tennis_sync.py`.

1.  **Review and Refine `main()` function:**
    * Ensure the overall flow matches the blueprint:
        * Setup (Args, Logging, Constants)
        * Get Credentials Path
        * Authenticate Google (`service` object)
        * Get Date Range
        * Initialize `all_parsed_data = {}`
        * Loop through dates:
            * Fetch (with throttle) -> Parse -> Merge into `all_parsed_data`
            * Handle fetch/parse errors per day (log and exit immediately as per spec).
        * Consolidate all parsed data (`desired_state = consolidate_booked_slots(...)`)
        * Loop through `CALENDAR_IDS`:
            * Check location validity (`CALENDAR_IDS`, `desired_state`) - log warning/skip if needed.
            * Calculate overall time range (`time_min_iso`, `time_max_iso`) for fetching.
            * Fetch existing events (handle calendar access errors - log warning/skip location).
            * Diff events.
            * Log planned changes.
            * Loop: Create events (handle API errors - log and exit).
            * Loop: Delete events (handle API errors - log and exit, except 404/410).
    * **Top-Level Error Handling:** Wrap the entire core logic inside `main()` (from authentication onwards) in a `try...except Exception as e:` block.
        * In the `except` block, log a general "Script failed due to unhandled exception" message, log the exception `e` with traceback (`logging.exception(e)`), and ensure the script exits with a non-zero status code (`sys.exit(1)`).
    * Ensure logging provides clear context about which location/date is being processed, actions taken (fetching, parsing, creating, deleting), and whether it's a dry run.
    * Add a final "Sync process completed." log message at the very end of the `try` block.
2.  **Review Imports and Requirements:** Ensure all necessary libraries (`requests`, `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`, `pytz`) are imported and listed (e.g., in a `requirements.txt`).
3.  **Add Script Docstring:** Ensure the top-level docstring clearly explains what the script does, its dependencies (credentials file, environment variables), and how to run it (including arguments).
4.  **Generate `pytest` integration-style tests** for `main()` (optional but recommended):
    * These tests are more complex and involve mocking multiple functions called by `main`.
    * Mock `argparse.ArgumentParser.parse_args`.
    * Mock `authenticate_google` to return a mock service.
    * Mock `get_sync_date_range` to return a fixed, short date range.
    * Mock `Workspace_hayward_data` to return predefined data for the test dates.
    * Mock `parse_reservation_data` to return predefined parsed structures.
    * Mock `Workspace_calendar_events` to return predefined existing events.
    * Mock `create_google_event` and `delete_google_event`.
    * **Test Scenarios:**
        * Test the full flow with a mix of create/delete actions (`dry_run=False`). Verify the create/delete mocks are called with the expected arguments based on the mocked input data.
        * Test the `dry_run=True` flow. Verify create/delete mocks are *not* called.
        * Test skipping a location if its `calendar_id` is missing in `CALENDAR_IDS` (by adjusting the mocked `CALENDAR_IDS`).
        * Test skipping a location if `Workspace_calendar_events` raises a 404 error (mock the exception).
        * Test script exit on critical errors (e.g., mock `Workspace_hayward_data` to raise an error). Use `pytest.raises(SystemExit)`.
    * These tests verify the orchestration logic glues the unit-tested components together correctly.

```