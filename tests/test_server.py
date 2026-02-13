"""Tests for renfield-mcp-calendar server."""

import textwrap
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from renfield_mcp_calendar import config as config_module
from renfield_mcp_calendar import server
from renfield_mcp_calendar.backends.base import CalendarEvent
from renfield_mcp_calendar.config import CalendarAccount


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module-level state between tests."""
    server._accounts = {}
    server._backends = {}
    yield
    server._accounts = {}
    server._backends = {}


def _make_account(
    name: str = "test",
    label: str = "Test Calendar",
    cal_type: str = "ews",
    config: dict | None = None,
) -> CalendarAccount:
    if config is None:
        config = {
            "ews_url": "https://exchange.example.com/EWS/Exchange.asmx",
            "username_env": "CAL_TEST_USER",
            "password_env": "CAL_TEST_PASS",
        }
    return CalendarAccount(name=name, label=label, type=cal_type, config=config)


def _make_event(
    id: str = "evt-1",
    calendar: str = "test",
    title: str = "Team Meeting",
    start: datetime | None = None,
    end: datetime | None = None,
) -> CalendarEvent:
    return CalendarEvent(
        id=id,
        calendar=calendar,
        title=title,
        start=start or datetime(2026, 2, 13, 14, 0),
        end=end or datetime(2026, 2, 13, 15, 0),
    )


def _setup_mock_backend(events: list[CalendarEvent] | None = None) -> AsyncMock:
    """Create a mock backend and install it."""
    backend = AsyncMock()
    backend.list_events = AsyncMock(return_value=events or [])
    backend.create_event = AsyncMock()
    backend.update_event = AsyncMock()
    backend.delete_event = AsyncMock(return_value=True)
    backend.get_event = AsyncMock()
    return backend


# ---------------------------------------------------------------------------
# Config loading tests
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_valid_ews_config(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cal.yaml"
        cfg.write_text(textwrap.dedent("""\
            calendars:
              - name: work
                label: "Firmenkalender"
                type: ews
                ews_url: "https://exchange.example.com/EWS/Exchange.asmx"
                username_env: CAL_WORK_USER
                password_env: CAL_WORK_PASS
        """))
        monkeypatch.setenv("CAL_WORK_USER", "user@example.com")
        monkeypatch.setenv("CAL_WORK_PASS", "secret")
        monkeypatch.setattr(config_module, "CONFIG_PATH", str(cfg))
        accounts = config_module.load_config()
        assert "work" in accounts
        assert accounts["work"].type == "ews"
        assert accounts["work"].label == "Firmenkalender"

    def test_valid_google_config(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cal.yaml"
        cfg.write_text(textwrap.dedent("""\
            calendars:
              - name: family
                label: "Familienkalender"
                type: google
                calendar_id: "primary"
                credentials_file: "/config/google_creds.json"
                token_file: "/data/google_token.json"
        """))
        monkeypatch.setattr(config_module, "CONFIG_PATH", str(cfg))
        accounts = config_module.load_config()
        assert "family" in accounts
        assert accounts["family"].type == "google"

    def test_valid_caldav_config(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cal.yaml"
        cfg.write_text(textwrap.dedent("""\
            calendars:
              - name: verein
                label: "Vereinskalender"
                type: caldav
                url: "https://nextcloud.example.com/remote.php/dav/calendars/user/verein/"
                username_env: CAL_VEREIN_USER
                password_env: CAL_VEREIN_PASS
        """))
        monkeypatch.setenv("CAL_VEREIN_USER", "user")
        monkeypatch.setenv("CAL_VEREIN_PASS", "pass")
        monkeypatch.setattr(config_module, "CONFIG_PATH", str(cfg))
        accounts = config_module.load_config()
        assert "verein" in accounts
        assert accounts["verein"].type == "caldav"

    def test_multiple_calendars(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cal.yaml"
        cfg.write_text(textwrap.dedent("""\
            calendars:
              - name: work
                type: ews
                ews_url: "https://exchange.example.com/EWS/Exchange.asmx"
                username_env: CAL_WORK_USER
                password_env: CAL_WORK_PASS
              - name: family
                type: google
                credentials_file: "/config/creds.json"
              - name: verein
                type: caldav
                url: "https://nextcloud.example.com/dav/"
                username_env: CAL_V_USER
                password_env: CAL_V_PASS
        """))
        monkeypatch.setenv("CAL_WORK_USER", "u")
        monkeypatch.setenv("CAL_WORK_PASS", "p")
        monkeypatch.setenv("CAL_V_USER", "u")
        monkeypatch.setenv("CAL_V_PASS", "p")
        monkeypatch.setattr(config_module, "CONFIG_PATH", str(cfg))
        accounts = config_module.load_config()
        assert len(accounts) == 3

    def test_missing_config_file(self, monkeypatch):
        monkeypatch.setattr(config_module, "CONFIG_PATH", "/nonexistent/config.yaml")
        accounts = config_module.load_config()
        assert accounts == {}

    def test_duplicate_name_raises(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cal.yaml"
        cfg.write_text(textwrap.dedent("""\
            calendars:
              - name: work
                type: ews
                ews_url: "https://exchange.example.com/EWS/Exchange.asmx"
                username_env: U
                password_env: P
              - name: work
                type: ews
                ews_url: "https://exchange2.example.com/EWS/Exchange.asmx"
                username_env: U2
                password_env: P2
        """))
        monkeypatch.setattr(config_module, "CONFIG_PATH", str(cfg))
        with pytest.raises(ValueError, match="Duplicate"):
            config_module.load_config()

    def test_unknown_type_raises(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cal.yaml"
        cfg.write_text(textwrap.dedent("""\
            calendars:
              - name: test
                type: outlook365
                url: "https://example.com"
        """))
        monkeypatch.setattr(config_module, "CONFIG_PATH", str(cfg))
        with pytest.raises(ValueError, match="unknown type"):
            config_module.load_config()

    def test_ews_missing_url_raises(self, tmp_path, monkeypatch):
        cfg = tmp_path / "cal.yaml"
        cfg.write_text(textwrap.dedent("""\
            calendars:
              - name: work
                type: ews
                username_env: U
                password_env: P
        """))
        monkeypatch.setattr(config_module, "CONFIG_PATH", str(cfg))
        with pytest.raises(ValueError, match="ews_url"):
            config_module.load_config()


# ---------------------------------------------------------------------------
# Tool tests: list_calendars
# ---------------------------------------------------------------------------

class TestListCalendars:
    async def test_no_calendars(self):
        result = await server.list_calendars()
        assert "error" in result

    async def test_with_calendars(self):
        server._accounts = {
            "work": _make_account("work", "Firmenkalender"),
            "family": _make_account("family", "Familie", "google", {"credentials_file": "/x"}),
        }
        result = await server.list_calendars()
        assert len(result["calendars"]) == 2
        assert result["calendars"][0]["name"] == "work"
        assert result["calendars"][1]["name"] == "family"


# ---------------------------------------------------------------------------
# Tool tests: list_events
# ---------------------------------------------------------------------------

class TestListEvents:
    async def test_no_calendars(self):
        result = await server.list_events()
        assert result["count"] == 0
        assert result["calendars_queried"] == []

    async def test_unknown_calendar(self):
        server._accounts = {"work": _make_account("work")}
        result = await server.list_events(calendar="nonexistent")
        assert "error" in result
        assert "nonexistent" in result["error"]

    async def test_single_calendar(self):
        server._accounts = {"work": _make_account("work")}
        events = [_make_event("e1", "work", "Meeting")]
        backend = _setup_mock_backend(events)
        server._backends = {"work": backend}

        result = await server.list_events(calendar="work", start="2026-02-13", end="2026-02-13")
        assert result["count"] == 1
        assert result["events"][0]["title"] == "Meeting"
        assert result["calendars_queried"] == ["work"]

    async def test_all_calendars_merged(self):
        server._accounts = {
            "work": _make_account("work"),
            "family": _make_account("family"),
        }
        work_events = [_make_event("e1", "work", "Work Meeting", datetime(2026, 2, 13, 14, 0))]
        family_events = [_make_event("e2", "family", "Zahnarzt", datetime(2026, 2, 13, 10, 0))]

        work_backend = _setup_mock_backend(work_events)
        family_backend = _setup_mock_backend(family_events)
        server._backends = {"work": work_backend, "family": family_backend}

        result = await server.list_events(start="2026-02-13", end="2026-02-13")
        assert result["count"] == 2
        # Sorted chronologically: Zahnarzt (10:00) before Work Meeting (14:00)
        assert result["events"][0]["title"] == "Zahnarzt"
        assert result["events"][1]["title"] == "Work Meeting"

    async def test_invalid_start_date(self):
        server._accounts = {"work": _make_account("work")}
        result = await server.list_events(start="not-a-date")
        assert "error" in result

    async def test_backend_error_partial_results(self):
        server._accounts = {
            "work": _make_account("work"),
            "family": _make_account("family"),
        }
        work_backend = _setup_mock_backend([_make_event("e1", "work", "Meeting")])
        family_backend = AsyncMock()
        family_backend.list_events = AsyncMock(side_effect=Exception("Connection failed"))
        server._backends = {"work": work_backend, "family": family_backend}

        result = await server.list_events(start="2026-02-13")
        assert result["count"] == 1  # Partial results from work
        assert len(result["errors"]) == 1  # Error from family


# ---------------------------------------------------------------------------
# Tool tests: create_event
# ---------------------------------------------------------------------------

class TestCreateEvent:
    async def test_create_success(self):
        server._accounts = {"work": _make_account("work")}
        created = _make_event("new-1", "work", "New Meeting")
        backend = _setup_mock_backend()
        backend.create_event = AsyncMock(return_value=created)
        server._backends = {"work": backend}

        result = await server.create_event(
            calendar="work",
            title="New Meeting",
            start="2026-02-14T14:00:00",
            end="2026-02-14T15:00:00",
        )
        assert result["success"] is True
        assert result["event"]["title"] == "New Meeting"

    async def test_create_unknown_calendar(self):
        server._accounts = {"work": _make_account("work")}
        result = await server.create_event(
            calendar="nonexistent",
            title="Test",
            start="2026-02-14T14:00:00",
            end="2026-02-14T15:00:00",
        )
        assert "error" in result

    async def test_create_invalid_dates(self):
        server._accounts = {"work": _make_account("work")}
        result = await server.create_event(
            calendar="work",
            title="Test",
            start="invalid",
            end="2026-02-14T15:00:00",
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# Tool tests: delete_event
# ---------------------------------------------------------------------------

class TestDeleteEvent:
    async def test_delete_success(self):
        server._accounts = {"work": _make_account("work")}
        backend = _setup_mock_backend()
        backend.delete_event = AsyncMock(return_value=True)
        server._backends = {"work": backend}

        result = await server.delete_event(calendar="work", event_id="evt-1")
        assert result["success"] is True

    async def test_delete_not_found(self):
        server._accounts = {"work": _make_account("work")}
        backend = _setup_mock_backend()
        backend.delete_event = AsyncMock(return_value=False)
        server._backends = {"work": backend}

        result = await server.delete_event(calendar="work", event_id="nonexistent")
        assert "error" in result


# ---------------------------------------------------------------------------
# Tool tests: get_event
# ---------------------------------------------------------------------------

class TestGetEvent:
    async def test_get_success(self):
        server._accounts = {"work": _make_account("work")}
        event = _make_event("e1", "work", "Team Meeting")
        backend = _setup_mock_backend()
        backend.get_event = AsyncMock(return_value=event)
        server._backends = {"work": backend}

        result = await server.get_event(calendar="work", event_id="e1")
        assert result["event"]["title"] == "Team Meeting"

    async def test_get_unknown_calendar(self):
        server._accounts = {"work": _make_account("work")}
        result = await server.get_event(calendar="nonexistent", event_id="e1")
        assert "error" in result


# ---------------------------------------------------------------------------
# Tool tests: update_event
# ---------------------------------------------------------------------------

class TestUpdateEvent:
    async def test_update_success(self):
        server._accounts = {"work": _make_account("work")}
        updated = _make_event("e1", "work", "Updated Meeting")
        backend = _setup_mock_backend()
        backend.update_event = AsyncMock(return_value=updated)
        server._backends = {"work": backend}

        result = await server.update_event(calendar="work", event_id="e1", title="Updated Meeting")
        assert result["success"] is True
        assert result["event"]["title"] == "Updated Meeting"

    async def test_update_no_fields(self):
        server._accounts = {"work": _make_account("work")}
        result = await server.update_event(calendar="work", event_id="e1")
        assert "error" in result
        assert "No fields" in result["error"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_event_to_dict(self):
        event = _make_event("e1", "work", "Test")
        d = server._event_to_dict(event)
        assert d["id"] == "e1"
        assert d["calendar"] == "work"
        assert d["title"] == "Test"
        assert isinstance(d["start"], str)

    def test_validate_calendar_no_accounts(self):
        result = server._validate_calendar("work")
        assert result is not None
        assert "error" in result

    def test_validate_calendar_unknown(self):
        server._accounts = {"work": _make_account("work")}
        result = server._validate_calendar("nonexistent")
        assert "nonexistent" in result["error"]

    def test_validate_calendar_valid(self):
        server._accounts = {"work": _make_account("work")}
        result = server._validate_calendar("work")
        assert result is None


# ---------------------------------------------------------------------------
# Tool tests: get_pending_notifications
# ---------------------------------------------------------------------------

class TestGetPendingNotifications:
    async def test_no_calendars(self):
        """No calendars configured — returns empty list."""
        result = await server.get_pending_notifications()
        assert result == []

    async def test_no_upcoming_events(self):
        """Calendar has no events in lookahead window."""
        server._accounts = {"work": _make_account("work")}
        backend = _setup_mock_backend(events=[])
        server._backends = {"work": backend}

        result = await server.get_pending_notifications(lookahead_minutes=45)
        assert result == []

    async def test_event_at_30_minutes(self):
        """Event starting in ~30 minutes should generate info notification."""
        from datetime import timedelta

        now = datetime.now()
        event_start = now + timedelta(minutes=30)
        event_end = event_start + timedelta(hours=1)

        server._accounts = {"work": _make_account("work", label="Firmenkalender")}
        event = _make_event("e1", "work", "Team Meeting", start=event_start, end=event_end)
        backend = _setup_mock_backend(events=[event])
        server._backends = {"work": backend}

        result = await server.get_pending_notifications(lookahead_minutes=45)
        assert len(result) == 1
        assert result[0]["event_type"] == "calendar.reminder_upcoming"
        assert result[0]["title"] == "Team Meeting"
        assert "30 Minuten" in result[0]["message"]
        assert "Firmenkalender" in result[0]["message"]
        assert result[0]["urgency"] == "info"
        assert result[0]["dedup_key"] == "calendar:work:e1:30min"
        assert result[0]["data"]["calendar"] == "work"
        assert result[0]["data"]["event_id"] == "e1"

    async def test_event_at_5_minutes(self):
        """Event starting in ~5 minutes should generate warning notification."""
        from datetime import timedelta

        now = datetime.now()
        event_start = now + timedelta(minutes=5)
        event_end = event_start + timedelta(hours=1)

        server._accounts = {"work": _make_account("work", label="Firmenkalender")}
        event = _make_event("e2", "work", "Standup", start=event_start, end=event_end)
        backend = _setup_mock_backend(events=[event])
        server._backends = {"work": backend}

        result = await server.get_pending_notifications(lookahead_minutes=45)
        assert len(result) == 1
        assert result[0]["urgency"] == "warning"
        assert "5 Minuten" in result[0]["message"]
        assert result[0]["dedup_key"] == "calendar:work:e2:5min"

    async def test_event_too_far_away(self):
        """Event starting in 40 minutes — no 30min or 5min threshold match."""
        from datetime import timedelta

        now = datetime.now()
        event_start = now + timedelta(minutes=40)
        event_end = event_start + timedelta(hours=1)

        server._accounts = {"work": _make_account("work")}
        event = _make_event("e3", "work", "Far Away", start=event_start, end=event_end)
        backend = _setup_mock_backend(events=[event])
        server._backends = {"work": backend}

        result = await server.get_pending_notifications(lookahead_minutes=45)
        assert result == []

    async def test_multiple_calendars(self):
        """Events from multiple calendars should be included."""
        from datetime import timedelta

        now = datetime.now()
        event1_start = now + timedelta(minutes=30)
        event2_start = now + timedelta(minutes=5)

        server._accounts = {
            "work": _make_account("work", label="Firmenkalender"),
            "family": _make_account("family", label="Familienkalender", cal_type="google", config={
                "calendar_id": "primary",
                "credentials_file": "/tmp/creds.json",
                "token_file": "/tmp/token.json",
            }),
        }
        event1 = _make_event("e1", "work", "Meeting", start=event1_start, end=event1_start + timedelta(hours=1))
        event2 = _make_event("e2", "family", "Zahnarzt", start=event2_start, end=event2_start + timedelta(hours=1))

        backend1 = _setup_mock_backend(events=[event1])
        backend2 = _setup_mock_backend(events=[event2])
        server._backends = {"work": backend1, "family": backend2}

        result = await server.get_pending_notifications(lookahead_minutes=45)
        assert len(result) == 2
        calendars = {r["data"]["calendar"] for r in result}
        assert calendars == {"work", "family"}

    async def test_backend_failure_graceful(self):
        """If one backend fails, others still return notifications."""
        from datetime import timedelta

        now = datetime.now()
        event_start = now + timedelta(minutes=30)

        server._accounts = {
            "work": _make_account("work", label="Firmenkalender"),
            "family": _make_account("family", label="Familienkalender", cal_type="google", config={
                "calendar_id": "primary",
                "credentials_file": "/tmp/creds.json",
                "token_file": "/tmp/token.json",
            }),
        }

        good_backend = _setup_mock_backend(events=[
            _make_event("e1", "work", "Meeting", start=event_start, end=event_start + timedelta(hours=1))
        ])
        bad_backend = _setup_mock_backend()
        bad_backend.list_events = AsyncMock(side_effect=Exception("Connection failed"))

        server._backends = {"work": good_backend, "family": bad_backend}

        result = await server.get_pending_notifications(lookahead_minutes=45)
        assert len(result) == 1
        assert result[0]["data"]["calendar"] == "work"

    async def test_notification_has_tts_flag(self):
        """Notifications should include tts=True for TTS delivery."""
        from datetime import timedelta

        now = datetime.now()
        event_start = now + timedelta(minutes=30)

        server._accounts = {"work": _make_account("work")}
        event = _make_event("e1", "work", "Test", start=event_start, end=event_start + timedelta(hours=1))
        backend = _setup_mock_backend(events=[event])
        server._backends = {"work": backend}

        result = await server.get_pending_notifications()
        assert result[0]["tts"] is True
