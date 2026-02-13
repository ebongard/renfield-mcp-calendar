"""Google Calendar API backend."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any

from .base import CalendarEvent

logger = logging.getLogger("renfield-mcp-calendar")


class GoogleCalendarBackend:
    """Calendar backend for Google Calendar via Google API."""

    def __init__(self, calendar_name: str, config: dict[str, Any]):
        self._name = calendar_name
        self._config = config
        self._service = None  # Lazy init
        self._calendar_id = config.get("calendar_id", "primary")

    def _get_service(self):
        """Lazy-initialize Google Calendar API service with auto-refresh."""
        if self._service is not None:
            return self._service

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/calendar"]

        creds = None
        token_file = self._config.get("token_file", "/data/google_calendar_token.json")
        credentials_file = self._config["credentials_file"]

        # Load existing token
        if os.path.isfile(token_file):
            with open(token_file, "r") as f:
                token_data = json.load(f)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)

        # Refresh or obtain new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Persist refreshed token
                with open(token_file, "w") as f:
                    json.dump(json.loads(creds.to_json()), f)
                logger.info("Google token refreshed for '%s'", self._name)
            elif os.path.isfile(credentials_file):
                raise ValueError(
                    f"Calendar '{self._name}': Google token not found or expired. "
                    f"Run: python -m renfield_mcp_calendar --auth google --calendar {self._name}"
                )
            else:
                raise ValueError(
                    f"Calendar '{self._name}': credentials file not found: {credentials_file}"
                )

        self._service = build("calendar", "v3", credentials=creds)
        logger.info("Google Calendar connected: %s (calendar_id=%s)", self._name, self._calendar_id)
        return self._service

    def _list_events_sync(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        service = self._get_service()
        time_min = start.isoformat() + "Z" if not start.tzinfo else start.isoformat()
        time_max = end.isoformat() + "Z" if not end.tzinfo else end.isoformat()

        events_result = (
            service.events()
            .list(
                calendarId=self._calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )

        events = []
        for item in events_result.get("items", []):
            start_raw = item.get("start", {})
            end_raw = item.get("end", {})

            # All-day events use 'date', timed events use 'dateTime'
            all_day = "date" in start_raw and "dateTime" not in start_raw

            if all_day:
                from dateutil.parser import parse as parse_dt
                ev_start = parse_dt(start_raw["date"])
                ev_end = parse_dt(end_raw.get("date", start_raw["date"]))
            else:
                from dateutil.parser import parse as parse_dt
                ev_start = parse_dt(start_raw.get("dateTime", ""))
                ev_end = parse_dt(end_raw.get("dateTime", ""))

            events.append(CalendarEvent(
                id=item["id"],
                calendar=self._name,
                title=item.get("summary", "(Kein Titel)"),
                start=ev_start.replace(tzinfo=None) if ev_start.tzinfo else ev_start,
                end=ev_end.replace(tzinfo=None) if ev_end.tzinfo else ev_end,
                description=item.get("description", ""),
                location=item.get("location", ""),
                all_day=all_day,
            ))
        return events

    def _create_event_sync(
        self, title: str, start: datetime, end: datetime, description: str, location: str
    ) -> CalendarEvent:
        service = self._get_service()
        body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Berlin"},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location

        result = service.events().insert(calendarId=self._calendar_id, body=body).execute()
        logger.info("Google event created: %s in '%s'", title, self._name)

        return CalendarEvent(
            id=result["id"],
            calendar=self._name,
            title=title,
            start=start,
            end=end,
            description=description,
            location=location,
        )

    def _update_event_sync(self, event_id: str, **kwargs: object) -> CalendarEvent:
        service = self._get_service()
        event = service.events().get(calendarId=self._calendar_id, eventId=event_id).execute()

        if "title" in kwargs:
            event["summary"] = kwargs["title"]
        if "start" in kwargs:
            event["start"] = {"dateTime": kwargs["start"].isoformat(), "timeZone": "Europe/Berlin"}
        if "end" in kwargs:
            event["end"] = {"dateTime": kwargs["end"].isoformat(), "timeZone": "Europe/Berlin"}
        if "description" in kwargs:
            event["description"] = kwargs["description"]
        if "location" in kwargs:
            event["location"] = kwargs["location"]

        result = service.events().update(calendarId=self._calendar_id, eventId=event_id, body=event).execute()

        from dateutil.parser import parse as parse_dt
        ev_start = parse_dt(result["start"].get("dateTime", result["start"].get("date", "")))
        ev_end = parse_dt(result["end"].get("dateTime", result["end"].get("date", "")))

        return CalendarEvent(
            id=result["id"],
            calendar=self._name,
            title=result.get("summary", ""),
            start=ev_start.replace(tzinfo=None) if ev_start.tzinfo else ev_start,
            end=ev_end.replace(tzinfo=None) if ev_end.tzinfo else ev_end,
            description=result.get("description", ""),
            location=result.get("location", ""),
        )

    def _delete_event_sync(self, event_id: str) -> bool:
        service = self._get_service()
        service.events().delete(calendarId=self._calendar_id, eventId=event_id).execute()
        return True

    def _get_event_sync(self, event_id: str) -> CalendarEvent:
        service = self._get_service()
        item = service.events().get(calendarId=self._calendar_id, eventId=event_id).execute()

        start_raw = item.get("start", {})
        end_raw = item.get("end", {})
        all_day = "date" in start_raw and "dateTime" not in start_raw

        from dateutil.parser import parse as parse_dt
        if all_day:
            ev_start = parse_dt(start_raw["date"])
            ev_end = parse_dt(end_raw.get("date", start_raw["date"]))
        else:
            ev_start = parse_dt(start_raw.get("dateTime", ""))
            ev_end = parse_dt(end_raw.get("dateTime", ""))

        return CalendarEvent(
            id=item["id"],
            calendar=self._name,
            title=item.get("summary", ""),
            start=ev_start.replace(tzinfo=None) if ev_start.tzinfo else ev_start,
            end=ev_end.replace(tzinfo=None) if ev_end.tzinfo else ev_end,
            description=item.get("description", ""),
            location=item.get("location", ""),
            all_day=all_day,
        )

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
