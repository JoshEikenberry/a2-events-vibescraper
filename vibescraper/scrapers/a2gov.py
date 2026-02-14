"""Scraper for City of Ann Arbor public meetings (Legistar API)."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

from vibescraper.models import Event, LOOKAHEAD_DAYS, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

logger = logging.getLogger(__name__)

API_BASE = "https://webapi.legistar.com/v1/annarbor/events"


@ScraperRegistry.register
class A2GovScraper(BaseScraper):
    """Scrapes City of Ann Arbor public meeting calendar via Legistar API.

    The Legistar system at a2gov.legistar.com exposes a public JSON API
    that returns structured meeting data for city boards and commissions.
    """

    name = "a2gov"
    base_url = "https://a2gov.legistar.com/"

    def _scrape_impl(self) -> list[Event]:
        events: list[Event] = []
        cutoff = lookahead_cutoff()

        today = date.today().isoformat()
        url = (
            f"{API_BASE}"
            f"?$filter=EventDate ge datetime'{today}'"
            f"&$orderby=EventDate"
        )
        resp = self.fetch(url)

        if resp is None:
            return events

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            logger.error("a2gov: invalid JSON response")
            return events

        if not isinstance(data, list):
            logger.error("a2gov: unexpected response format (not a list)")
            return events

        for item in data:
            event = self._parse_item(item)
            if event and event.date <= cutoff:
                events.append(event)

        logger.info("a2gov: scraped %d event(s)", len(events))
        return events

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_item(self, item: dict) -> Optional[Event]:
        """Convert a single Legistar event object to our Event model."""
        try:
            body_name = (item.get("EventBodyName") or "").strip()
            if not body_name:
                return None

            event_date_raw = item.get("EventDate", "")
            if not event_date_raw:
                return None

            # EventDate is like "2026-02-12T00:00:00"
            iso_date = event_date_raw[:10]

            # EventTime is like "7:00 PM"
            time_str = None
            event_time = (item.get("EventTime") or "").strip()
            if event_time:
                try:
                    time_str = self.to_24h(event_time)
                except ValueError:
                    logger.debug("a2gov: could not parse time %r", event_time)

            venue = (item.get("EventLocation") or "").strip() or None

            description = self.truncate(
                (item.get("EventAgendaStatusName") or "").strip()
            )

            event_id = item.get("EventId", "")
            source_url = f"https://a2gov.legistar.com/"

            return Event(
                title=body_name,
                date=iso_date,
                time=time_str,
                venue=venue,
                description=description or None,
                source_url=source_url,
                source_name="City of Ann Arbor",
                tags=["Government", "Meeting"],
            )
        except Exception:
            logger.exception("Failed to parse a2gov event item")
            return None
