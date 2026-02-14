"""Scraper for Blind Pig music venue events."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag

from vibescraper.models import Event, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

logger = logging.getLogger(__name__)

BASE = "https://blindpigmusic.com"
CALENDAR_URL = f"{BASE}/calendar/"
VENUE = "Blind Pig"
ADDRESS = "208 S. 1st St, Ann Arbor, MI 48104"
MAX_PAGES = 10  # safety limit


@ScraperRegistry.register
class BlindPigScraper(BaseScraper):
    """Scrapes the Blind Pig calendar page.

    Events are listed at https://blindpigmusic.com/calendar/ with pagination
    at /page/2/, /page/3/, etc.  Each event link has a title attribute
    containing "Event Title - DD/MM/YY".  Door times and price info appear
    in the event text as "Doors 8:00pm | 18 and up | $14.35".
    """

    name = "blindpig"
    base_url = CALENDAR_URL

    def _scrape_impl(self) -> list[Event]:
        events: list[Event] = []
        cutoff = lookahead_cutoff()
        page = 1
        hit_cutoff = False

        while page <= MAX_PAGES:
            url = CALENDAR_URL if page == 1 else f"{BASE}/page/{page}/"
            resp = self.fetch(url)

            if resp is None:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            event_links = soup.select("a[href*='/tm-event/']")

            if not event_links:
                break

            for link in event_links:
                event = self._parse_event(link)
                if event:
                    if event.date > cutoff:
                        hit_cutoff = True
                        continue
                    events.append(event)

            if hit_cutoff:
                logger.debug("Reached 90-day cutoff (%s), stopping.", cutoff)
                break

            if not self._has_next_page(soup):
                break

            page += 1

        logger.info("Blind Pig: scraped %d event(s) across %d page(s)", len(events), page)
        return events

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_event(self, link: Tag) -> Optional[Event]:
        """Extract an Event from a single event link element."""
        try:
            title_attr = link.get("title", "")
            href = link.get("href", "")
            source_url = self.absolute_url(BASE, href)

            title, date_str = self._parse_title_attr(title_attr)
            if not title or not date_str:
                return None

            # Walk siblings / parent to find detail text with door time
            detail_text = self._find_detail_text(link)
            time_str = self._extract_door_time(detail_text) if detail_text else None

            # Build description from detail text
            description = detail_text.strip() if detail_text else None

            return Event(
                title=title,
                date=date_str,
                time=time_str,
                venue=VENUE,
                address=ADDRESS,
                description=description,
                source_url=source_url,
                source_name="Blind Pig",
                tags=["Live Music"],
            )
        except Exception:
            logger.exception("Failed to parse Blind Pig event")
            return None

    @staticmethod
    def _parse_title_attr(title_attr: str) -> tuple[Optional[str], Optional[str]]:
        """Parse title attribute like "Event Title - DD/MM/YY".

        Returns (title, iso_date) or (None, None) on failure.
        """
        if not title_attr:
            return None, None

        # Split on last " - " to handle titles containing dashes
        match = re.match(r"^(.+)\s+-\s+(\d{2}/\d{2}/\d{2})$", title_attr)
        if not match:
            return title_attr.strip() or None, None

        title = match.group(1).strip()
        date_part = match.group(2)

        try:
            dt = datetime.strptime(date_part, "%d/%m/%y")
            iso_date = dt.strftime("%Y-%m-%d")
        except ValueError:
            return title, None

        return title, iso_date

    @staticmethod
    def _find_detail_text(link: Tag) -> Optional[str]:
        """Find the detail/info text near an event link.

        Looks at the parent container for text containing door time or
        price info.
        """
        parent = link.parent
        if parent is None:
            return None

        # Walk up a couple levels to find the event container
        for _ in range(3):
            if parent is None:
                break
            text = parent.get_text(separator=" ", strip=True)
            if text and re.search(r"doors?\s+\d", text, re.IGNORECASE):
                return text
            parent = parent.parent

        return None

    @staticmethod
    def _extract_door_time(text: str) -> Optional[str]:
        """Extract door time from text like 'Doors 8:00pm' or 'Doors 8pm'.

        Returns 24-hour time string or None.
        """
        match = re.search(r"doors?\s+(\d{1,2}(?::\d{2})?\s*[ap]m)", text, re.IGNORECASE)
        if not match:
            return None

        raw = match.group(1).strip().lower().replace(" ", "")
        # Normalize "8pm" -> "8:00pm"
        if ":" not in raw:
            raw = re.sub(r"(\d+)(am|pm)", r"\1:00\2", raw)

        return BaseScraper.to_24h(raw)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    @staticmethod
    def _has_next_page(soup: BeautifulSoup) -> bool:
        """Check if a 'Next' pagination link exists."""
        next_link = soup.find("a", string=re.compile(r"next", re.IGNORECASE))
        if next_link:
            return True
        # Also check for a rel="next" link
        return soup.find("a", attrs={"rel": "next"}) is not None
