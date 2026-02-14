"""Scraper for University of Michigan events (JSON API)."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

from vibescraper.models import Event, LOOKAHEAD_DAYS, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

logger = logging.getLogger(__name__)

API_BASE = "https://events.umich.edu/list/json"


@ScraperRegistry.register
class UMichScraper(BaseScraper):
    """Scrapes University of Michigan events via the public JSON API.

    The events.umich.edu API returns structured JSON data, making this
    scraper simpler than HTML-based ones. Events are fetched for the
    next 90 days in a single request.
    """

    name = "umich"
    base_url = "https://events.umich.edu"

    def _scrape_impl(self) -> list[Event]:
        events: list[Event] = []
        cutoff = lookahead_cutoff()

        today = date.today().isoformat()
        end_date = (date.today() + timedelta(days=LOOKAHEAD_DAYS)).isoformat()

        # The API supports a range parameter with ISO dates
        url = f"{API_BASE}?v=2&range={today}-{end_date}"
        resp = self.fetch(url)

        if resp is None:
            return events

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            logger.error("UMich: invalid JSON response")
            return events

        if not isinstance(data, list):
            logger.error("UMich: unexpected response format (not a list)")
            return events

        for item in data:
            event = self._parse_item(item)
            if event and event.date <= cutoff:
                events.append(event)

        logger.info("UMich: scraped %d event(s)", len(events))
        return events

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_item(self, item: dict) -> Optional[Event]:
        """Convert a single JSON event object to our Event model."""
        try:
            title = (item.get("combined_title") or item.get("event_title") or "").strip()
            if not title:
                return None

            iso_date = item.get("date_start", "")
            if not iso_date:
                return None

            # Time: "12:00:00" -> "12:00"
            time_start = item.get("time_start", "")
            time_str = time_start[:5] if time_start else None

            end_time = None
            if item.get("has_end_time"):
                time_end = item.get("time_end", "")
                end_time = time_end[:5] if time_end else None

            # Venue: prefer building_name, fall back to location_name
            building = (item.get("building_name") or "").strip()
            location = (item.get("location_name") or "").strip()
            room = (item.get("room") or "").strip()

            # Skip if location looks like a URL (virtual-only event)
            venue = building or location
            if venue.startswith("http"):
                venue = "Virtual"
            if room and venue != "Virtual":
                venue = f"{venue}, {room}"

            # Description (truncate for storage)
            description = self.truncate((item.get("description") or "").strip())

            # Source URL
            source_url = item.get("permalink", "")

            # Tags from event_type and tags list
            tags: list[str] = []
            event_type = (item.get("event_type") or "").strip()
            if event_type:
                tags.append(event_type)
            for tag in item.get("tags", []):
                if isinstance(tag, str) and tag not in tags:
                    tags.append(tag)
            tags = tags[:5]

            return Event(
                title=title,
                date=iso_date,
                time=time_str,
                end_time=end_time,
                venue=venue or "University of Michigan",
                description=description or None,
                source_url=source_url,
                source_name="U-M",
                tags=tags,
            )
        except Exception:
            logger.exception("Failed to parse UMich event item")
            return None
