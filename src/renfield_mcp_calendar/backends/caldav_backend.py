"""CalDAV backend (Nextcloud, ownCloud, Radicale, etc.)."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from .base import CalendarEvent

logger = logging.getLogger("renfield-mcp-calendar")


class CalDAVBackend:
    """Calendar backend for CalDAV servers (Nextcloud, etc.)."""

    def __init__(self, calendar_name: str, config: dict[str, Any]):
        self._name = calendar_name
        self._config = config
        self._calendar = None  # Lazy init

    def _get_calendar(self):
        """Lazy-initialize CalDAV client and calendar."""
        if self._calendar is not None:
            return self._calendar

        import caldav

        username = os.environ.get(self._config["username_env"], "")
        password = os.environ.get(self._config["password_env"], "")
        if not username or not password:
            raise ValueError(
                f"Calendar '{self._name}': CalDAV credentials not set "
                f"({self._config['username_env']}, {self._config['password_env']})"
            )

        url = self._config["url"]
        client = caldav.DAVClient(url=url, username=username, password=password)

        # If URL points to a specific calendar, use it directly
        # Otherwise, get principal and find calendar by name
        calendar_name_filter = self._config.get("calendar_name")
        if calendar_name_filter:
            principal = client.principal()
            calendars = principal.calendars()
            for cal in calendars:
                if cal.name == calendar_name_filter:
                    self._calendar = cal
                    break
            if self._calendar is None:
                available = [c.name for c in calendars]
                raise ValueError(
                    f"Calendar '{self._name}': CalDAV calendar '{calendar_name_filter}' not found. "
                    f"Available: {available}"
                )
        else:
            # URL points directly to a calendar
            self._calendar = caldav.Calendar(client=client, url=url)

        logger.info("CalDAV connected: %s → %s", self._name, url)
        return self._calendar

    def _parse_vevent(self, vevent: Any) -> CalendarEvent:
        """Parse a VEVENT component into a CalendarEvent."""
        summary = str(vevent.get("summary", "(Kein Titel)")) if vevent.get("summary") else "(Kein Titel)"
        description = str(vevent.get("description", "")) if vevent.get("description") else ""
        location = str(vevent.get("location", "")) if vevent.get("location") else ""

        dtstart = vevent.get("dtstart")
        dtend = vevent.get("dtend")

        ev_start = dtstart.dt if dtstart else datetime.now()
        ev_end = dtend.dt if dtend else ev_start

        # Detect all-day events (date without time)
        from datetime import date as date_type
        all_day = isinstance(ev_start, date_type) and not isinstance(ev_start, datetime)

        if all_day:
            ev_start = datetime(ev_start.year, ev_start.month, ev_start.day)
            if isinstance(ev_end, date_type) and not isinstance(ev_end, datetime):
                ev_end = datetime(ev_end.year, ev_end.month, ev_end.day)

        # Strip timezone info for consistent handling
        if isinstance(ev_start, datetime) and ev_start.tzinfo:
            ev_start = ev_start.replace(tzinfo=None)
        if isinstance(ev_end, datetime) and ev_end.tzinfo:
            ev_end = ev_end.replace(tzinfo=None)

        uid = str(vevent.get("uid", "")) if vevent.get("uid") else ""

        return CalendarEvent(
            id=uid,
            calendar=self._name,
            title=summary,
            start=ev_start,
            end=ev_end,
            description=description,
            location=location,
            all_day=all_day,
        )

    def _list_events_sync(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        cal = self._get_calendar()
        results = cal.date_search(start=start, end=end, expand=True)

        events = []
        for event_obj in results:
            vevents = event_obj.icalendar_instance.walk("VEVENT")
            for vevent in vevents:
                events.append(self._parse_vevent(vevent))

        # Sort chronologically
        events.sort(key=lambda e: e.start)
        return events

    def _create_event_sync(
        self, title: str, start: datetime, end: datetime, description: str, location: str
    ) -> CalendarEvent:
        import uuid

        cal = self._get_calendar()
        uid = str(uuid.uuid4())

        vcal = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//renfield-mcp-calendar//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"SUMMARY:{title}\r\n"
        )
        if description:
            vcal += f"DESCRIPTION:{description}\r\n"
        if location:
            vcal += f"LOCATION:{location}\r\n"
        vcal += "END:VEVENT\r\nEND:VCALENDAR\r\n"

        cal.save_event(vcal)
        logger.info("CalDAV event created: %s in '%s'", title, self._name)

        return CalendarEvent(
            id=uid,
            calendar=self._name,
            title=title,
            start=start,
            end=end,
            description=description,
            location=location,
        )

    def _update_event_sync(self, event_id: str, **kwargs: object) -> CalendarEvent:
        cal = self._get_calendar()
        event_obj = cal.event_by_uid(event_id)
        vevents = event_obj.icalendar_instance.walk("VEVENT")
        if not vevents:
            raise ValueError(f"Event not found: {event_id}")

        vevent = vevents[0]
        if "title" in kwargs:
            vevent["summary"] = kwargs["title"]
        if "start" in kwargs:
            from icalendar import vDatetime
            vevent["dtstart"] = vDatetime(kwargs["start"])
        if "end" in kwargs:
            from icalendar import vDatetime
            vevent["dtend"] = vDatetime(kwargs["end"])
        if "description" in kwargs:
            vevent["description"] = kwargs["description"]
        if "location" in kwargs:
            vevent["location"] = kwargs["location"]

        event_obj.save()
        return self._parse_vevent(vevent)

    def _delete_event_sync(self, event_id: str) -> bool:
        cal = self._get_calendar()
        try:
            event_obj = cal.event_by_uid(event_id)
            event_obj.delete()
            return True
        except Exception:
            return False

    def _get_event_sync(self, event_id: str) -> CalendarEvent:
        cal = self._get_calendar()
        event_obj = cal.event_by_uid(event_id)
        vevents = event_obj.icalendar_instance.walk("VEVENT")
        if not vevents:
            raise ValueError(f"Event not found: {event_id}")
        return self._parse_vevent(vevents[0])

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._list_events_sync, start, end)

    async def create_event(
        self, title: str, start: datetime, end: datetime, description: str = "", location: str = ""
    ) -> CalendarEvent:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._create_event_sync, title, start, end, description, location)

    async def update_event(self, event_id: str, **kwargs: object) -> CalendarEvent:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._update_event_sync(event_id, **kwargs))

    async def delete_event(self, event_id: str) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._delete_event_sync, event_id)

    async def get_event(self, event_id: str) -> CalendarEvent:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_event_sync, event_id)
