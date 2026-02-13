"""Base types and protocol for calendar backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class CalendarEvent:
    """Unified calendar event representation."""

    id: str
    calendar: str  # Account name (work, family, verein)
    title: str
    start: datetime
    end: datetime
    description: str = ""
    location: str = ""
    all_day: bool = False


@runtime_checkable
class CalendarBackend(Protocol):
    """Protocol that all calendar backends must satisfy."""

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent: ...

    async def update_event(self, event_id: str, **kwargs: object) -> CalendarEvent: ...

    async def delete_event(self, event_id: str) -> bool: ...

    async def get_event(self, event_id: str) -> CalendarEvent: ...
