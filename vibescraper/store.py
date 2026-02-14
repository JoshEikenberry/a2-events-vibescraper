"""JSON-backed event store."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from vibescraper.dedup import deduplicate
from vibescraper.models import Event, lookahead_cutoff

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data")
EVENTS_FILE = "events.json"
ARCHIVE_FILE = "archive.json"


class EventStore:
    """Manages persistence of events in structured JSON files.

    File layout:
        data/
            events.json   — all current/future events
            archive.json  — past events, keyed by month ("2026-01")
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self.data_dir / EVENTS_FILE
        self._archive_path = self.data_dir / ARCHIVE_FILE

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_events(self) -> list[Event]:
        """Load all current events from disk."""
        return self._load_file(self._events_path)

    def load_archive(self) -> list[Event]:
        """Load all archived events from disk."""
        return self._load_file(self._archive_path)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_events(self, events: list[Event]) -> None:
        """Persist current events to disk (sorted chronologically)."""
        events = sorted(events, key=lambda e: e.sort_key)
        self._save_file(self._events_path, events)

    def save_archive(self, events: list[Event]) -> None:
        """Persist archived events to disk (sorted chronologically)."""
        events = sorted(events, key=lambda e: e.sort_key)
        self._save_file(self._archive_path, events)

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def upsert_events(self, incoming: list[Event]) -> tuple[int, int]:
        """Merge incoming events into the store.

        Events beyond the 90-day lookahead window are silently dropped.

        Returns:
            (added, updated) counts.
        """
        cutoff = lookahead_cutoff()
        existing = {e.event_id: e for e in self.load_events()}
        added = 0
        updated = 0

        for event in incoming:
            if event.date > cutoff:
                continue
            if event.event_id in existing:
                # Overwrite with freshest data
                existing[event.event_id] = event
                updated += 1
            else:
                existing[event.event_id] = event
                added += 1

        # Deduplicate before saving
        all_events = list(existing.values())
        deduped, dupes_removed = deduplicate(all_events)

        self.save_events(deduped)
        logger.info(
            "Upsert complete: %d added, %d updated, %d duplicate(s) merged",
            added, updated, dupes_removed,
        )
        return added, updated

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def archive_past_events(self) -> int:
        """Move events with dates before today into the archive.

        Returns:
            Number of events archived.
        """
        today = date.today().isoformat()
        events = self.load_events()
        archive = self.load_archive()

        current = []
        newly_archived = []
        for event in events:
            if event.date < today:
                newly_archived.append(event)
            else:
                current.append(event)

        if not newly_archived:
            logger.info("No past events to archive.")
            return 0

        archive_ids = {e.event_id for e in archive}
        for event in newly_archived:
            if event.event_id not in archive_ids:
                archive.append(event)

        self.save_events(current)
        self.save_archive(archive)
        logger.info("Archived %d event(s).", len(newly_archived))
        return len(newly_archived)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return summary counts."""
        return {
            "current_events": len(self.load_events()),
            "archived_events": len(self.load_archive()),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_file(path: Path) -> list[Event]:
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [Event.from_dict(item) for item in raw]

    @staticmethod
    def _save_file(path: Path, events: list[Event]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in events], f, indent=2, ensure_ascii=False)
