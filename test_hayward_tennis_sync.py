import datetime
import json
import time

import pytest
from unittest.mock import MagicMock, patch

import hayward_tennis_sync as sync

# Test for get_sync_date_range
def test_get_sync_date_range():
    num_days = 80
    dates = sync.get_sync_date_range(num_days)
    today = datetime.date.today()
    expected_first = (today + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    assert dates[0] == expected_first
    assert len(dates) == num_days

# Test for fetch_hayward_data with monkeypatch for requests.get and time.sleep
class FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code
    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception("Network error")

def test_fetch_hayward_data(monkeypatch):
    fake_content = b'{"headers": {}, "body": {"date": "2025-04-20", "locations": []}}'
    
    def fake_post(url, **kwargs):
        assert "quickreservation/availability" in url, f"URL is {url}"
        return FakeResponse(fake_content)
    
    def fake_sleep(seconds):
        pass
    
    monkeypatch.setattr(time, "sleep", fake_sleep)
    monkeypatch.setattr(sync.session, "post", fake_post)
    
    result = sync.fetch_hayward_data("2025-04-20", 1.5, None)
    assert json.loads(result) == json.loads(fake_content)

# Test parse_reservation_data with valid JSON
def test_parse_reservation_data_valid():
    sample_json = {
        "body": {
            "availability": {
                "time_slots": ["09:00-09:30", "09:30-10:00"],
                "resources": [
                    {
                        "resource_name": "Mervin - Tennis Court 1",
                        "time_slot_details": [
                            {"status": 1},
                            {"status": 0}
                        ]
                    }
                ]
            }
        }
    }
    json_data = json.dumps(sample_json).encode("utf-8")
    result = sync.parse_reservation_data(json_data, "2025-04-20")
    assert "2025-04-20" in result
    assert "Mervin" in result["2025-04-20"]
    assert "Court 1" in result["2025-04-20"]["Mervin"]
    assert result["2025-04-20"]["Mervin"]["Court 1"]["09:00"] is True
    assert result["2025-04-20"]["Mervin"]["Court 1"]["09:30"] is False

# Test parse_reservation_data with invalid JSON should raise ValueError
def test_parse_reservation_data_invalid():
    invalid_json = b'{"invalid": "data"}'
    with pytest.raises(ValueError):
        sync.parse_reservation_data(invalid_json)

# Test consolidate_booked_slots with adjacent and non-adjacent bookings
def test_consolidate_booked_slots():
    parsed_data = {
        "2025-04-20": {
            "Mervin": {
                "Court 1": {
                    "09:00": True,
                    "09:30": True,
                    "10:00": False,
                    "10:30": True
                }
            }
        }
    }
    result = sync.consolidate_booked_slots(parsed_data)
    assert "Mervin" in result
    events = result["Mervin"].get("Court 1", [])
    # Expect 2 consolidated event ranges: one for the consecutive slots and one for the isolated slot
    assert len(events) == 2
    for start, end in events:
        assert "T" in start and "T" in end

# Test authenticate_google by mocking Google auth libraries
def test_authenticate_google(monkeypatch):
    dummy_service = object()
    class DummyCredentials:
        def authorize(self, http):
            return http
    def fake_from_service_account_file(path, scopes):
        return DummyCredentials()
    def fake_build(api, version, credentials):
        assert api == "calendar"
        assert version == "v3"
        return dummy_service
    import google.oauth2.service_account as service_account
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file", fake_from_service_account_file)
    monkeypatch.setattr(sync, "build", fake_build)
    result = sync.authenticate_google("dummy_path.json")
    assert result is dummy_service

# Test fetch_calendar_events by mocking service.events().list().execute()
def test_fetch_calendar_events():
    fake_events = [
        {"id": "1", "summary": "Court 1", "start": {"dateTime": "2025-04-20T09:00:00Z"}, "end": {"dateTime": "2025-04-20T10:00:00Z"}},
        {"id": "2", "summary": "Other Event", "start": {"dateTime": "2025-04-20T11:00:00Z"}, "end": {"dateTime": "2025-04-20T12:00:00Z"}}
    ]
    fake_response_page = {"items": fake_events, "nextPageToken": None}
    fake_list = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=fake_response_page)))
    fake_events_method = MagicMock()
    fake_events_method.list = MagicMock(return_value=fake_list())
    fake_service = MagicMock()
    fake_service.events = MagicMock(return_value=fake_events_method)
    
    events = sync.fetch_calendar_events(fake_service, "dummy_calendar", "2025-04-20T00:00:00", "2025-04-21T00:00:00")
    # Only events with summary starting with "Court " should be returned
    assert len(events) == 1
    assert events[0]["summary"] == "Court 1"

# Test diff_events function
def test_diff_events():
    desired_slots = {
        "Court 1": [("2025-04-20T09:00:00-07:00", "2025-04-20T10:00:00-07:00")],
        "Court 2": [("2025-04-20T10:00:00-07:00", "2025-04-20T11:00:00-07:00")]
    }
    existing_events = [
        {"id": "a", "summary": "Court 1", "start": "2025-04-20T09:00:00-07:00", "end": "2025-04-20T10:00:00-07:00"},
        {"id": "b", "summary": "Court 2", "start": "2025-04-20T10:00:00-07:00", "end": "2025-04-20T11:00:00-07:00"},
        {"id": "c", "summary": "Court 3", "start": "2025-04-20T12:00:00-07:00", "end": "2025-04-20T13:00:00-07:00"}
    ]
    to_create, to_delete = sync.diff_events(desired_slots, existing_events, "Mervin")
    # In this test, the desired events match two existing events exactly, so nothing to create.
    # The extra event "Court 3" should be scheduled for deletion.
    assert to_create == []
    assert to_delete == ["c"]

# Test create_google_event with dry-run and actual run
def test_create_google_event(monkeypatch):
    dummy_service = MagicMock()
    # Dry-run test: function should log and return None
    result = sync.create_google_event(dummy_service, "dummy_calendar", "Court 1",
                                      "2025-04-20T09:00:00Z", "2025-04-20T10:00:00Z",
                                      "America/Los_Angeles", True)
    assert result is None

    # Actual run test: simulate insertion returning an event
    dummy_event = {"id": "event123"}
    fake_insert = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=dummy_event)))
    dummy_events = MagicMock()
    dummy_events.insert = MagicMock(return_value=fake_insert())
    dummy_service.events = MagicMock(return_value=dummy_events)
    result = sync.create_google_event(dummy_service, "dummy_calendar", "Court 1",
                                      "2025-04-20T09:00:00Z", "2025-04-20T10:00:00Z",
                                      "America/Los_Angeles", False)
    assert result == dummy_event

# Test delete_google_event with dry-run and actual run
def test_delete_google_event(monkeypatch):
    dummy_service = MagicMock()
    # Dry-run test: should not attempt deletion
    dummy_service.events = MagicMock()
    sync.delete_google_event(dummy_service, "dummy_calendar", "event123", True)

    # Actual run test: simulate successful deletion
    fake_delete = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=None)))
    dummy_events = MagicMock()
    dummy_events.delete = MagicMock(return_value=fake_delete())
    dummy_service.events = MagicMock(return_value=dummy_events)
    sync.delete_google_event(dummy_service, "dummy_calendar", "event123", False)
    dummy_events.delete.assert_called_with(calendarId="dummy_calendar", eventId="event123")
