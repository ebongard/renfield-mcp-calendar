"""Exchange Web Services (EWS) backend via exchangelib."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from .base import CalendarBackend, CalendarEvent

logger = logging.getLogger("renfield-mcp-calendar")


class EWSBackend:
    """Calendar backend for Microsoft Exchange via EWS."""

    def __init__(self, calendar_name: str, config: dict[str, Any]):
        self._name = calendar_name
        self._config = config
        self._account = None  # Lazy init

    def _get_account(self):
        """Lazy-initialize exchangelib Account."""
        if self._account is not None:
            return self._account

        from exchangelib import Account, Configuration, Credentials, DELEGATE

        username = os.environ.get(self._config["username_env"], "")
        password = os.environ.get(self._config["password_env"], "")
        if not username or not password:
            raise ValueError(
                f"Calendar '{self._name}': EWS credentials not set "
                f"({self._config['username_env']}, {self._config['password_env']})"
            )

        ews_url = self._config["ews_url"]
        credentials = Credentials(username=username, password=password)
        ews_config = Configuration(
            server=ews_url.split("//")[1].split("/")[0],  # Extract hostname
            credentials=credentials,
            service_endpoint=ews_url,
        )

        self._account = Account(
            primary_smtp_address=self._config.get("email", username),
            config=ews_config,
            autodiscover=False,
            access_type=DELEGATE,
        )
        logger.info("EWS connected: %s → %s", self._name, ews_url)
        return self._account

    def _list_events_sync(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        from exchangelib import EWSDateTime, EWSTimeZone

        account = self._get_account()
        tz = EWSTimeZone.localzone()
        ews_start = EWSDateTime.from_datetime(start.astimezone(tz))
        ews_end = EWSDateTime.from_datetime(end.astimezone(tz))

        items = account.calendar.filter(start__lt=ews_end, end__gt=ews_start).order_by("start")

        events = []
        for item in items:
            events.append(CalendarEvent(
                id=item.id,
                calendar=self._name,
                title=item.subject or "(Kein Titel)",
                start=item.start.astimezone().replace(tzinfo=None) if item.start else start,
                end=item.end.astimezone().replace(tzinfo=None) if item.end else end,
                description=item.body or "" if hasattr(item, "body") else "",
                location=item.location or "" if hasattr(item, "location") else "",
                all_day=item.is_all_day if hasattr(item, "is_all_day") else False,
            ))
        return events

    def _create_event_sync(
        self, title: str, start: datetime, end: datetime, description: str, location: str
    ) -> CalendarEvent:
        from exchangelib import CalendarItem as EWSCalendarItem, EWSDateTime, EWSTimeZone

        account = self._get_account()
        tz = EWSTimeZone.localzone()

        item = EWSCalendarItem(
            account=account,
            folder=account.calendar,
            subject=title,
            start=EWSDateTime.from_datetime(start.astimezone(tz)),
            end=EWSDateTime.from_datetime(end.astimezone(tz)),
            body=description,
            location=location,
        )
        item.save()
        logger.info("EWS event created: %s in '%s'", title, self._name)

        return CalendarEvent(
            id=item.id,
            calendar=self._name,
            title=title,
            start=start,
            end=end,
            description=description,
            location=location,
        )

    def _update_event_sync(self, event_id: str, **kwargs: object) -> CalendarEvent:
        account = self._get_account()
        items = list(account.calendar.filter(id=event_id))
        if not items:
            raise ValueError(f"Event not found: {event_id}")

        item = items[0]
        if "title" in kwargs:
            item.subject = kwargs["title"]
        if "start" in kwargs:
            from exchangelib import EWSDateTime, EWSTimeZone
            tz = EWSTimeZone.localzone()
            item.start = EWSDateTime.from_datetime(kwargs["start"].astimezone(tz))
        if "end" in kwargs:
            from exchangelib import EWSDateTime, EWSTimeZone
            tz = EWSTimeZone.localzone()
            item.end = EWSDateTime.from_datetime(kwargs["end"].astimezone(tz))
        if "description" in kwargs:
            item.body = kwargs["description"]
        if "location" in kwargs:
            item.location = kwargs["location"]
        item.save()

        return CalendarEvent(
            id=item.id,
            calendar=self._name,
            title=item.subject or "",
            start=item.start.astimezone().replace(tzinfo=None) if item.start else datetime.now(),
            end=item.end.astimezone().replace(tzinfo=None) if item.end else datetime.now(),
            description=str(item.body) if item.body else "",
            location=item.location or "",
        )

    def _delete_event_sync(self, event_id: str) -> bool:
        account = self._get_account()
        items = list(account.calendar.filter(id=event_id))
        if not items:
            return False
        items[0].delete()
        return True

    def _get_event_sync(self, event_id: str) -> CalendarEvent:
        account = self._get_account()
        items = list(account.calendar.filter(id=event_id))
        if not items:
            raise ValueError(f"Event not found: {event_id}")
        item = items[0]
        return CalendarEvent(
            id=item.id,
            calendar=self._name,
            title=item.subject or "",
            start=item.start.astimezone().replace(tzinfo=None) if item.start else datetime.now(),
            end=item.end.astimezone().replace(tzinfo=None) if item.end else datetime.now(),
            description=str(item.body) if item.body else "",
            location=item.location or "",
            all_day=item.is_all_day if hasattr(item, "is_all_day") else False,
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
