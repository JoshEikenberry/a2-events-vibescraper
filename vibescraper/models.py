"""Event data model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

# Maximum number of days into the future to consider.
LOOKAHEAD_DAYS = 90


def lookahead_cutoff() -> str:
    """Return the ISO date string for the furthest future date we care about."""
    return (date.today() + timedelta(days=LOOKAHEAD_DAYS)).isoformat()


@dataclass
class Event:
    """A single calendar event."""

    title: str
    date: str  # ISO 8601 date: "2026-03-15"
    time: Optional[str] = None  # 24-hr time: "19:30", or None if all-day
    end_time: Optional[str] = None  # Optional end time: "21:00"
    venue: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None  # Link back to original listing
    source_name: Optional[str] = None  # e.g. "AADL", "The Ark"
    tags: list[str] = field(default_factory=list)
    event_id: str = field(default="", init=False)

    def __post_init__(self) -> None:
        """Generate a stable event ID from core fields."""
        self.event_id = self._generate_id()

    def _generate_id(self) -> str:
        """Create a deterministic hash from title + date + venue.

        This is used as the primary key for storage and dedup.
        """
        key = f"{self.title.strip().lower()}|{self.date}|{(self.venue or '').strip().lower()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        """Deserialize from a plain dict."""
        # Pop event_id so __post_init__ regenerates it
        data = dict(data)
        data.pop("event_id", None)
        return cls(**data)

    @property
    def sort_key(self) -> tuple:
        """Key for chronological sorting."""
        return (self.date, self.time or "00:00", self.title.lower())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self.event_id == other.event_id

    def __hash__(self) -> int:
        return hash(self.event_id)

    def __repr__(self) -> str:
        time_str = f" {self.time}" if self.time else ""
        return f"<Event '{self.title}' on {self.date}{time_str} @ {self.venue or '?'}>"
