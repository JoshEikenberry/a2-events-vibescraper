"""Scraper for Ann Arbor Comedy Showcase events."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag

from vibescraper.models import Event, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

logger = logging.getLogger(__name__)

BASE = "https://www.aacomedy.com"
VENUE = "Ann Arbor Comedy Showcase"
ADDRESS = "212 S. Fourth Ave, Ann Arbor, MI 48104"


@ScraperRegistry.register
class AAComedyScraper(BaseScraper):
    """Scrapes Ann Arbor Comedy Showcase events from the homepage.

    The Comedy Showcase lists upcoming shows on their main page with
    comedian names, dates, and ticket links. Shows are typically
    Thursday-Saturday with occasional special events.
    """

    name = "aacomedy"
    base_url = BASE

    def _scrape_impl(self) -> list[Event]:
        events: list[Event] = []
        cutoff = lookahead_cutoff()

        resp = self.fetch(BASE)
        if resp is None:
            return events

        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for event sections - the site has sections for each show
        # Try multiple strategies to find event data

        # Strategy 1: Find links to etix.com (ticket links) and work backwards
        ticket_links = soup.select('a[href*="etix.com/ticket/e/"]')
        seen_urls: set[str] = set()

        for link in ticket_links:
            ticket_url = link.get("href", "")
            if ticket_url in seen_urls:
                continue
            seen_urls.add(ticket_url)

            # Walk up to find the containing section/div
            container = self._find_event_container(link)
            if container:
                event = self._parse_container(container, ticket_url)
                if event and event.date <= cutoff:
                    events.append(event)

        # Strategy 2: Look for structured event data in JSON-LD
        for item in self.iter_jsonld_of_type(soup, "Event"):
            event = self._parse_jsonld(item)
            if event and event.date <= cutoff:
                events.append(event)

        logger.info("AA Comedy: scraped %d event(s)", len(events))
        return events

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _find_event_container(self, link: Tag) -> Optional[Tag]:
        """Walk up from a ticket link to find the event's containing section."""
        # Walk up through parents looking for a section/div with enough content
        for parent in link.parents:
            if parent.name in ("section", "div", "article"):
                # Check if this container has enough text to be an event
                text = parent.get_text(strip=True)
                if len(text) > 50 and any(
                    month in text
                    for month in [
                        "January",
                        "February",
                        "March",
                        "April",
                        "May",
                        "June",
                        "July",
                        "August",
                        "September",
                        "October",
                        "November",
                        "December",
                    ]
                ):
                    return parent
        return None

    def _parse_container(self, container: Tag, ticket_url: str) -> Optional[Event]:
        """Extract event data from a containing section."""
        try:
            text = container.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            if not lines:
                return None

            # Find title: usually a heading or the first substantial text
            title = None
            headings = container.select("h1, h2, h3, h4, h5")
            for h in headings:
                h_text = h.get_text(strip=True)
                if h_text and len(h_text) > 3 and not h_text.startswith("$"):
                    title = h_text
                    break

            if not title:
                # Use first non-trivial line
                for line in lines:
                    if (
                        len(line) > 5
                        and not line.startswith("$")
                        and not line.startswith("212")
                    ):
                        title = line
                        break

            if not title:
                return None

            # Find date: look for month names followed by day numbers
            iso_dates = self._extract_dates(text)
            if not iso_dates:
                return None

            # Use first date
            iso_date = iso_dates[0]

            # Find time: shows are typically at 7:15pm
            time_str = self._extract_time(text)

            # Build description from first ~200 chars of descriptive text
            desc_lines = [
                line
                for line in lines
                if len(line) > 20
                and not any(
                    skip in line.lower()
                    for skip in ["get tickets", "212 s", "734-", "etix.com"]
                )
                and line != title
            ]
            description = self.truncate(" ".join(desc_lines)) if desc_lines else None

            # Create event for first date
            return Event(
                title=title,
                date=iso_date,
                time=time_str or "19:15",  # Default showtime
                venue=VENUE,
                address=ADDRESS,
                description=description,
                source_url=ticket_url,
                source_name="AA Comedy Showcase",
                tags=["Comedy"],
            )
        except Exception:
            logger.exception("Failed to parse Comedy Showcase event")
            return None

    def _extract_dates(self, text: str) -> list[str]:
        """Extract ISO dates from text like 'February 12th 13th & 14th'."""
        dates: list[str] = []
        # Match month + day patterns
        month_pattern = (
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)"
        )
        # Look for "Month Nth" or "Month Nth Nth & Nth"
        match = re.search(
            rf"{month_pattern}\s+([\d]+)(?:st|nd|rd|th)?",
            text,
            re.IGNORECASE,
        )
        if not match:
            return dates

        month_name = match.group(1)
        # Find all day numbers after the month name up to the next non-date content
        rest = text[match.start() :]
        day_matches = re.findall(r"(\d{1,2})(?:st|nd|rd|th)?", rest[:60])

        # Determine year - use current year, bump to next if month has passed
        now = datetime.now()
        try:
            month_num = datetime.strptime(month_name, "%B").month
        except ValueError:
            return dates

        year = now.year
        if month_num < now.month:
            year += 1

        for day_str in day_matches:
            day = int(day_str)
            if 1 <= day <= 31:
                try:
                    dt = datetime(year, month_num, day)
                    dates.append(dt.strftime("%Y-%m-%d"))
                except ValueError:
                    continue

        return dates

    def _extract_time(self, text: str) -> Optional[str]:
        """Extract showtime from text like '7:15pm'."""
        match = re.search(r"(\d{1,2}:\d{2}\s*(?:am|pm))", text, re.IGNORECASE)
        if match:
            return self.to_24h(match.group(1))
        return None

    def _parse_jsonld(self, data: dict) -> Optional[Event]:
        """Parse a JSON-LD Event object."""
        try:
            title = data.get("name", "").strip()
            start = data.get("startDate", "")
            if not title or not start:
                return None

            dt = datetime.fromisoformat(start)
            return Event(
                title=title,
                date=dt.strftime("%Y-%m-%d"),
                time=dt.strftime("%H:%M") if "T" in start else "19:15",
                venue=VENUE,
                address=ADDRESS,
                source_url=data.get("url", BASE),
                source_name="AA Comedy Showcase",
                tags=["Comedy"],
            )
        except Exception:
            return None

