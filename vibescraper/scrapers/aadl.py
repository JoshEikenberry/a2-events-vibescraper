"""Scraper for Ann Arbor District Library (AADL) events."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag

from vibescraper.models import Event, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

logger = logging.getLogger(__name__)

BASE = "https://aadl.org"
UPCOMING_URL = f"{BASE}/events-feed/upcoming"
MAX_PAGES = 20  # safety limit


@ScraperRegistry.register
class AADLScraper(BaseScraper):
    """Scrapes the AADL upcoming-events feed.

    The feed lives at https://aadl.org/events-feed/upcoming and is paginated
    with 20 events per page (?page=0, ?page=1, …). The last page link is
    exposed in the pager so we know when to stop.
    """

    name = "aadl"
    base_url = UPCOMING_URL

    def _scrape_impl(self) -> list[Event]:
        events: list[Event] = []
        cutoff = lookahead_cutoff()
        page = 0
        hit_cutoff = False

        while page <= MAX_PAGES:
            url = f"{UPCOMING_URL}?page={page}"
            resp = self.fetch(url)

            if resp is None:
                # Request failed or session aborted — stop gracefully
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select(".views-row.search-result")

            if not rows:
                break

            for row in rows:
                event = self._parse_row(row)
                if event:
                    if event.date > cutoff:
                        hit_cutoff = True
                        continue
                    events.append(event)

            if hit_cutoff:
                logger.debug("Reached 90-day cutoff (%s), stopping.", cutoff)
                break

            # Check if there's a next page
            if not self._has_next_page(soup):
                break

            page += 1

        logger.info("AADL: scraped %d event(s) across %d page(s)", len(events), page + 1)
        return events

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_row(self, row: Tag) -> Optional[Event]:
        """Extract an Event from a single .views-row element."""
        try:
            body = row.select_one(".node-body")
            if not body:
                return None

            # Title & link
            link_tag = body.select_one("h2 a")
            if not link_tag:
                return None
            title = link_tag.get_text(strip=True)
            href = link_tag.get("href", "")
            source_url = f"{BASE}{href}" if href.startswith("/") else href

            # Category (from the icon column)
            category_tag = row.select_one(".mat-type-icon p")
            category = category_tag.get_text(strip=True) if category_tag else None

            # Info paragraph: date/time, venue, and optional age/grade
            p_tag = body.select_one("p")
            if not p_tag:
                return None

            parts = self.split_br(p_tag)
            # parts[0] = date/time line, parts[1] = venue, parts[2+] = age/misc

            date_str, time_str, end_time_str = self._parse_datetime(parts[0] if parts else "")
            venue = parts[1].strip() if len(parts) > 1 else None
            description = category

            if not date_str:
                logger.warning("Could not parse date for '%s'", title)
                return None

            tags = []
            if category:
                tags.append(category)
            # Age/grade info
            if len(parts) > 2:
                tags.append(parts[2].strip())

            return Event(
                title=title,
                date=date_str,
                time=time_str,
                end_time=end_time_str,
                venue=venue,
                description=description,
                source_url=source_url,
                source_name="AADL",
                tags=tags,
            )
        except Exception:
            logger.exception("Failed to parse AADL event row")
            return None

    @staticmethod
    def _parse_datetime(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Parse AADL date/time string into (iso_date, start_time_24h, end_time_24h).

        Input examples:
            "Thursday February 12, 2026: 10:30am to 11:00am"
            "Saturday March 1, 2026: 7:00pm to 9:00pm"
        """
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Pattern: "DayOfWeek Month Day, Year: StartTime to EndTime"
        match = re.match(
            r"(?:\w+\s+)?"  # optional day-of-week
            r"(\w+ \d{1,2},? \d{4})"  # month day, year
            r":\s*"
            r"(\d{1,2}:\d{2}(?:am|pm))"  # start time
            r"(?:\s+to\s+(\d{1,2}:\d{2}(?:am|pm)))?",  # optional end time
            text,
            re.IGNORECASE,
        )
        if not match:
            return None, None, None

        date_part = match.group(1).replace(",", ", ") if "," not in match.group(1) else match.group(1)
        # Normalize: ensure "February 12, 2026" format
        date_part = re.sub(r"\s+", " ", date_part).strip()
        # Handle missing comma: "February 12 2026" -> "February 12, 2026"
        date_part = re.sub(r"(\d)(,?\s+)(\d{4})", r"\1, \3", date_part)

        try:
            dt = datetime.strptime(date_part, "%B %d, %Y")
            iso_date = dt.strftime("%Y-%m-%d")
        except ValueError:
            return None, None, None

        start_time = AADLScraper.to_24h(match.group(2))
        end_time = AADLScraper.to_24h(match.group(3)) if match.group(3) else None

        return iso_date, start_time, end_time

    @staticmethod
    def _has_next_page(soup: BeautifulSoup) -> bool:
        """Check if a 'Next page' pager link exists."""
        return soup.select_one(".pager__item--next a") is not None
