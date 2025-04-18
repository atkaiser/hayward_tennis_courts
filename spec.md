# **Project Specification: `hayward_tennis_sync.py`**

## **Overview**

This script syncs Hayward Rec tennis court bookings into Google Calendar. It pulls structured reservation data from the Hayward Rec website (via a JSON endpoint), parses booked time slots, and updates dedicated Google Calendars per location. Bookings are consolidated and changes are diffed against the current calendar state.

---

## **Goals**

- Parse tennis court reservations from:  
  [https://anc.apm.activecommunities.com/haywardrec/reservation/landing/quick?locale=en-US&groupId=2](https://anc.apm.activecommunities.com/haywardrec/reservation/landing/quick?locale=en-US&groupId=2)
- Sync bookings for the **next 80 days** (excluding **today** and **tomorrow**)
- Update Google Calendars per location (e.g., **Mervin**, **Bay**)
- Only make changes when necessary (add/remove events if the booking state has changed)
- Support dry-run mode, verbose logging, and configurable throttling

---

## **Environment Assumptions**

- Script is run periodically (e.g., via cron) on a cloud server
- Python 3.8+ available
- You will manually create Google Calendars and Google Cloud service credentials

---

## **High-Level Architecture**

```
                 +---------------------------+
                 | Cron/Trigger              |
                 +-------------+-------------+
                               |
                               v
+------------------------------+------------------------------+
|                     hayward_tennis_sync.py                  |
+-------------------------------------------------------------+
|                                                             |
|  1. Config: Hardcoded calendar ID mappings                  |
|  2. Auth: Load service account credentials                  |
|  3. Fetch Days D+2 to D+81 from Hayward Rec JSON endpoint   |
|  4. Parse: Identify locations, courts, and booking slots    |
|  5. Convert: Consolidate booked slots into events           |
|  6. Compare: Diff with current calendar events              |
|  7. Sync: Create/delete calendar events as needed           |
|                                                             |
+-------------------------------------------------------------+
|   --dry-run        # Only log changes, no writes            |
|   --throttle=1.5   # Sleep between requests (in seconds)    |
+-------------------------------------------------------------+
```

---

## **Reservation Data Handling**

### **Source**
- Data is pulled from a **JSON API** (reverse-engineered from the dropdown selector on the Hayward Rec reservation page)
- Days queried: D+2 to D+81 (80 total)

### **Booking Detection**
- Reservation blocks are `<td>` elements in a table
- Booked = presence of `reserved` CSS class
- Time blocks are in **30-minute increments**

### **Consolidation**
- Adjacent booked 30-min blocks are merged into a single calendar event  
  _(e.g., 9:00–9:30, 9:30–10:00 → one 9:00–10:00 event)_

---

## **Calendar Integration**

### **Calendar Setup**
- One **Google Calendar per location** (e.g., "Mervin", "Bay")
- You will create and share these calendars manually with the service account
- Calendar IDs are **hardcoded** into the script:
  ```python
  CALENDAR_IDS = {
      "Mervin": "mervin@example.com",
      "Bay": "bay@example.com",
  }
  ```

### **Event Creation**
- Title: `"Court 1"`, `"Court 2"`, etc. (parsed dynamically from `"Mervin - Tennis Court 1"`)
- No description, attendees, or color customization
- Time zone: `America/Los_Angeles`
- Default calendar color

### **Event Lifecycle**
- Events are only created/removed **if there is a change**
- If a booked slot becomes available → **delete the corresponding event**
- If a new booking appears → **create new event**

---

## **Script Features**

| Feature                  | Description                                                                 |
|--------------------------|-----------------------------------------------------------------------------|
| `--dry-run`              | Prints planned changes without writing to calendars                        |
| `--throttle=<seconds>`   | Sleep between requests to avoid rate-limiting (default: 1.5s)              |
| Logging                  | Verbose to stdout — includes sync progress, actions, and any issues        |
| Court Filtering          | Only includes `"Tennis Court"` entries                                     |
| Missing Calendar         | Skips missing calendar IDs with a log message, does not fail script        |
| Unknown Location         | Ignores silently if a location is not in `CALENDAR_IDS`                    |
| Error Handling           | Fails immediately on first network or API error                            |
| Stateless                | No local caching; always compares against live Google Calendar data        |

---

## **Error Handling Strategy**

| Scenario                                  | Action                                                      |
|-------------------------------------------|-------------------------------------------------------------|
| Network/API error (Hayward or Google)     | Fail immediately, log and exit with non-zero code           |
| Calendar ID missing or inaccessible       | Log warning and skip location                               |
| Invalid response format                   | Raise clear error, fail immediately                         |
| Court appears without "Tennis Court"      | Ignore silently                                              |
| Unrecognized new location                 | Ignore silently                                              |

---

## **Google API Setup (Manual Steps)**

1. **Create a Google Cloud Project**
2. **Enable the Google Calendar API**
3. **Create a Service Account**  
   - Assign no specific roles
   - Download key as JSON
4. **Share each calendar with the service account email**
   - Calendar settings → Share with specific people
   - Give **Make changes to events** permission
5. **Place credentials JSON path in environment variable or hardcode path**

---

## **Testing Plan**

Script will include **unit tests** runnable with `pytest`, testing:

- ✅ Reservation JSON parsing (mock response)
- ✅ Grouping of 30-min slots into time ranges
- ✅ Mapping location → calendar ID
- ✅ Creating event payloads
- ✅ Diffing new slots vs existing events

You can run:
```bash
pytest hayward_tennis_sync.py
```

---

## **Filename and Structure**

- Script name: `hayward_tennis_sync.py`
- Self-contained in one file
- Optional section at the bottom:
  ```python
  if __name__ == "__main__":
      main()
  ```

---

## **Future Enhancements (Optional)**

- Retry logic with backoff
- Email or Slack alerts on failures
- HTML fallback scraping if API changes
- Command-line flag to override date range
