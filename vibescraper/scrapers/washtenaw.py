"""Scraper for Washtenaw County Parks & Recreation special events."""

from __future__ import annotations

import logging
from typing import Optional

from bs4 import BeautifulSoup, Tag

from vibescraper.models import Event, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

logger = logging.getLogger(__name__)

BASE = "https://www.washtenaw.org"
EVENTS_URL = f"{BASE}/873/Special-Events"


@ScraperRegistry.register
class WashtenawScraper(BaseScraper):
    """Scrapes Washtenaw County Parks & Recreation special events.

    The page at /873/Special-Events contains a simple HTML table with
    columns: Event | Location | Date.  Each event name is a link.
    """

    name = "washtenaw"
    base_url = EVENTS_URL

    def _scrape_impl(self) -> list[Event]:
        resp = self.fetch(EVENTS_URL)
        if resp is None:
            return []

        cutoff = lookahead_cutoff()
        soup = BeautifulSoup(resp.text, "html.parser")
        events: list[Event] = []

        table = soup.find("table")
        if not table:
            logger.warning("Washtenaw: no table found on page")
            return []

        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            event = self._parse_row(cells, cutoff)
            if event:
                events.append(event)

        logger.info("Washtenaw County: scraped %d event(s)", len(events))
        return events

    def _parse_row(self, cells: list[Tag], cutoff: str) -> Optional[Event]:
        """Parse a single table row into an Event."""
        try:
            link = cells[0].find("a")
            if not link:
                return None

            title = link.get_text(strip=True)
            if not title:
                return None

            href = link.get("href", "")
            source_url = self.absolute_url(BASE, href)

            venue = cells[1].get_text(strip=True) or None
            date_text = cells[2].get_text(strip=True)
            iso_date = self.parse_date_mdy(date_text)
            if not iso_date:
                logger.debug("Washtenaw: could not parse date %r for %r", date_text, title)
                return None

            if iso_date > cutoff:
                return None

            return Event(
                title=title,
                date=iso_date,
                venue=venue,
                source_url=source_url,
                source_name="Washtenaw County",
                tags=["Parks", "Community"],
            )
        except Exception:
            logger.exception("Failed to parse Washtenaw event row")
            return None
