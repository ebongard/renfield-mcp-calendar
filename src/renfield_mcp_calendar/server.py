#!/usr/bin/env python3
"""
renfield-mcp-calendar — Unified calendar MCP server.

Multi-calendar support via YAML config. Backends: Exchange EWS, Google Calendar, CalDAV.

Environment variables:
    CALENDAR_CONFIG — Path to calendar_accounts.yaml (default: /config/calendar_accounts.yaml)
"""

import asyncio
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from .backends.base import CalendarBackend, CalendarEvent
from .config import CalendarAccount, load_config

# MCP stdio servers must NEVER write to stdout — log to stderr only.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("renfield-mcp-calendar")


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_accounts: dict[str, CalendarAccount] = {}
_backends: dict[str, CalendarBackend] = {}


def _init_backend(account: CalendarAccount) -> CalendarBackend:
    """Create backend instance for a calendar account."""
    if account.type == "ews":
        from .backends.ews import EWSBackend
        return EWSBackend(account.name, account.config)
    elif account.type == "google":
        from .backends.google import GoogleCalendarBackend
        return GoogleCalendarBackend(account.name, account.config)
    elif account.type == "caldav":
        from .backends.caldav_backend import CalDAVBackend
        return CalDAVBackend(account.name, account.config)
    else:
        raise ValueError(f"Unknown backend type: {account.type}")


def _get_backend(calendar: str) -> CalendarBackend | None:
    """Get backend by calendar name. Lazy-initializes on first access."""
    if calendar not in _accounts:
        return None
    if calendar not in _backends:
        _backends[calendar] = _init_backend(_accounts[calendar])
    return _backends[calendar]


def _validate_calendar(calendar: str) -> dict | None:
    """Return error dict if calendar is invalid, None if valid."""
    if not _accounts:
        return {"error": "No calendars configured. Set CALENDAR_CONFIG env var."}
    if calendar not in _accounts:
        return {"error": f"Unknown calendar '{calendar}'. Available: {list(_accounts.keys())}"}
    return None


def _event_to_dict(event: CalendarEvent) -> dict[str, Any]:
    """Convert CalendarEvent to JSON-friendly dict."""
    return {
        "id": event.id,
        "calendar": event.calendar,
        "title": event.title,
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "description": event.description,
        "location": event.location,
        "all_day": event.all_day,
    }


def _parse_datetime(value: str) -> datetime:
    """Parse ISO 8601 datetime string. Supports date-only and datetime."""
    from dateutil.parser import parse as parse_dt
    return parse_dt(value)


# ---------------------------------------------------------------------------
# MCP Server + Tools
# ---------------------------------------------------------------------------

mcp = FastMCP("renfield-calendar")


@mcp.tool()
async def list_calendars() -> dict:
    """List all configured calendar accounts.

    Returns name, label, and type for each calendar.
    """
    if not _accounts:
        return {"error": "No calendars configured"}
    return {
        "calendars": [
            {"name": a.name, "label": a.label, "type": a.type}
            for a in _accounts.values()
        ]
    }


@mcp.tool()
async def list_events(
    calendar: str = "",
    start: str = "",
    end: str = "",
) -> dict:
    """List events from one or all calendars.

    If calendar is empty, returns merged events from ALL calendars sorted chronologically.
    Start/end default to today if not provided.

    Args:
        calendar: Calendar name (e.g. "work", "family"). Empty = all calendars.
        start: Start date/time (ISO 8601, e.g. "2026-02-13" or "2026-02-13T09:00:00"). Default: today 00:00.
        end: End date/time (ISO 8601). Default: today 23:59.
    """
    # Parse date range
    now = datetime.now()
    if start:
        try:
            dt_start = _parse_datetime(start)
        except Exception:
            return {"error": f"Invalid start date: {start}"}
    else:
        dt_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if end:
        try:
            dt_end = _parse_datetime(end)
        except Exception:
            return {"error": f"Invalid end date: {end}"}
    else:
        dt_end = dt_start.replace(hour=23, minute=59, second=59)

    # Determine which calendars to query
    if calendar:
        err = _validate_calendar(calendar)
        if err:
            return err
        calendars_to_query = [calendar]
    else:
        calendars_to_query = list(_accounts.keys())

    # Fetch events from all requested calendars
    all_events: list[CalendarEvent] = []
    errors: list[str] = []

    for cal_name in calendars_to_query:
        backend = _get_backend(cal_name)
        if not backend:
            errors.append(f"Backend not available: {cal_name}")
            continue
        try:
            events = await backend.list_events(dt_start, dt_end)
            all_events.extend(events)
        except Exception as e:
            logger.warning("Failed to fetch events from '%s': %s", cal_name, e)
            errors.append(f"{cal_name}: {e}")

    # Sort chronologically
    all_events.sort(key=lambda e: e.start)

    result: dict[str, Any] = {
        "calendars_queried": calendars_to_query,
        "start": dt_start.isoformat(),
        "end": dt_end.isoformat(),
        "count": len(all_events),
        "events": [_event_to_dict(e) for e in all_events],
    }
    if errors:
        result["errors"] = errors
    return result


@mcp.tool()
async def create_event(
    calendar: str,
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
) -> dict:
    """Create a new calendar event.

    Args:
        calendar: Calendar name (e.g. "work", "family", "verein")
        title: Event title/summary
        start: Start date/time (ISO 8601, e.g. "2026-02-14T14:00:00")
        end: End date/time (ISO 8601, e.g. "2026-02-14T15:00:00")
        description: Event description (optional)
        location: Event location (optional)
    """
    err = _validate_calendar(calendar)
    if err:
        return err

    try:
        dt_start = _parse_datetime(start)
    except Exception:
        return {"error": f"Invalid start date: {start}"}
    try:
        dt_end = _parse_datetime(end)
    except Exception:
        return {"error": f"Invalid end date: {end}"}

    backend = _get_backend(calendar)
    if not backend:
        return {"error": f"Backend not available: {calendar}"}

    try:
        event = await backend.create_event(title, dt_start, dt_end, description, location)
        return {"success": True, "event": _event_to_dict(event)}
    except Exception as e:
        return {"error": f"Failed to create event: {e}"}


@mcp.tool()
async def update_event(
    calendar: str,
    event_id: str,
    title: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    location: str = "",
) -> dict:
    """Update an existing calendar event. Only provided fields are changed.

    Args:
        calendar: Calendar name
        event_id: Event ID (from list_events or get_event)
        title: New title (optional)
        start: New start date/time (optional)
        end: New end date/time (optional)
        description: New description (optional)
        location: New location (optional)
    """
    err = _validate_calendar(calendar)
    if err:
        return err

    kwargs: dict[str, Any] = {}
    if title:
        kwargs["title"] = title
    if start:
        try:
            kwargs["start"] = _parse_datetime(start)
        except Exception:
            return {"error": f"Invalid start date: {start}"}
    if end:
        try:
            kwargs["end"] = _parse_datetime(end)
        except Exception:
            return {"error": f"Invalid end date: {end}"}
    if description:
        kwargs["description"] = description
    if location:
        kwargs["location"] = location

    if not kwargs:
        return {"error": "No fields to update"}

    backend = _get_backend(calendar)
    if not backend:
        return {"error": f"Backend not available: {calendar}"}

    try:
        event = await backend.update_event(event_id, **kwargs)
        return {"success": True, "event": _event_to_dict(event)}
    except Exception as e:
        return {"error": f"Failed to update event: {e}"}


@mcp.tool()
async def delete_event(calendar: str, event_id: str) -> dict:
    """Delete a calendar event.

    Args:
        calendar: Calendar name
        event_id: Event ID (from list_events or get_event)
    """
    err = _validate_calendar(calendar)
    if err:
        return err

    backend = _get_backend(calendar)
    if not backend:
        return {"error": f"Backend not available: {calendar}"}

    try:
        success = await backend.delete_event(event_id)
        if success:
            return {"success": True, "message": f"Event deleted from {calendar}"}
        return {"error": f"Event not found: {event_id}"}
    except Exception as e:
        return {"error": f"Failed to delete event: {e}"}


@mcp.tool()
async def get_event(calendar: str, event_id: str) -> dict:
    """Get a single event with full details.

    Args:
        calendar: Calendar name
        event_id: Event ID
    """
    err = _validate_calendar(calendar)
    if err:
        return err

    backend = _get_backend(calendar)
    if not backend:
        return {"error": f"Backend not available: {calendar}"}

    try:
        event = await backend.get_event(event_id)
        return {"event": _event_to_dict(event)}
    except Exception as e:
        return {"error": f"Failed to get event: {e}"}


# ---------------------------------------------------------------------------
# Google OAuth2 CLI helper
# ---------------------------------------------------------------------------

def _run_google_auth(calendar_name: str) -> None:
    """Interactive OAuth2 flow for Google Calendar. Run once to obtain token."""
    if calendar_name not in _accounts:
        print(f"Unknown calendar: {calendar_name}. Available: {list(_accounts.keys())}", file=sys.stderr)
        sys.exit(1)

    account = _accounts[calendar_name]
    if account.type != "google":
        print(f"Calendar '{calendar_name}' is type '{account.type}', not 'google'", file=sys.stderr)
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    credentials_file = account.config["credentials_file"]
    token_file = account.config.get("token_file", "/data/google_calendar_token.json")

    import json
    import os

    if not os.path.isfile(credentials_file):
        print(f"Credentials file not found: {credentials_file}", file=sys.stderr)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
    creds = flow.run_local_server(port=0)

    # Ensure directory exists
    os.makedirs(os.path.dirname(token_file) or ".", exist_ok=True)
    with open(token_file, "w") as f:
        json.dump(json.loads(creds.to_json()), f)

    print(f"Token saved to {token_file}", file=sys.stderr)
    print("Google Calendar authentication complete.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Entry point for console script and python -m."""
    global _accounts

    # Handle --auth flag for Google OAuth2 setup
    if "--auth" in sys.argv:
        _accounts = load_config()
        idx = sys.argv.index("--auth")
        provider = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if provider != "google":
            print(f"Only --auth google is supported, got: {provider}", file=sys.stderr)
            sys.exit(1)
        # Find calendar name
        cal_name = ""
        if "--calendar" in sys.argv:
            cal_idx = sys.argv.index("--calendar")
            cal_name = sys.argv[cal_idx + 1] if cal_idx + 1 < len(sys.argv) else ""
        if not cal_name:
            # Find first google calendar
            for name, acct in _accounts.items():
                if acct.type == "google":
                    cal_name = name
                    break
        if not cal_name:
            print("No Google calendar found in config", file=sys.stderr)
            sys.exit(1)
        _run_google_auth(cal_name)
        return

    _accounts = load_config()
    if _accounts:
        logger.info("Loaded %d calendar(s): %s", len(_accounts), list(_accounts.keys()))
    else:
        logger.warning("No calendars loaded (CALENDAR_CONFIG=%s)", __import__("os").environ.get("CALENDAR_CONFIG", ""))
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
