"""Scraper for Ann Arbor Observer community calendar events."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Optional

from bs4 import BeautifulSoup, Tag

from vibescraper.models import Event, LOOKAHEAD_DAYS, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

logger = logging.getLogger(__name__)

BASE = "https://annarborobserver.com"
CALENDAR_URL = f"{BASE}/events/"
MAX_PAGES = 30  # safety limit — scrape up to 30 days


@ScraperRegistry.register
class AAObserverScraper(BaseScraper):
    """Scrapes the Ann Arbor Observer community calendar.

    The Observer uses the Modern Events Calendar (MEC) WordPress plugin.
    Events are listed on daily views at ``/events/YYYY-MM-DD/``.  Each
    event card contains a title link (``/mc-events/event-slug/``), a time
    range, and optional cost/category labels.  We iterate day-by-day from
    today through the lookahead window (capped at MAX_PAGES days to be
    polite) and parse each day's listing page.
    """

    name = "aaobserver"
    base_url = CALENDAR_URL

    def _scrape_impl(self) -> list[Event]:
        events: list[Event] = []
        cutoff = lookahead_cutoff()
        today = date.today()

        for offset in range(MAX_PAGES):
            target = today + timedelta(days=offset)
            iso_date = target.isoformat()

            if iso_date > cutoff:
                logger.debug("Reached lookahead cutoff (%s), stopping.", cutoff)
                break

            url = f"{CALENDAR_URL}{iso_date}/"
            resp = self.fetch(url)

            if resp is None:
                break

            day_events = self._parse_day(resp.text, iso_date)
            events.extend(day_events)

        logger.info(
            "Ann Arbor Observer: scraped %d event(s) across %d day(s)",
            len(events),
            min(MAX_PAGES, (date.fromisoformat(cutoff) - today).days + 1),
        )
        return events

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_day(self, html: str, iso_date: str) -> list[Event]:
        """Parse all events from a single day's calendar page."""
        soup = BeautifulSoup(html, "html.parser")
        results: list[Event] = []

        # MEC event cards — try common MEC selectors
        cards = soup.select(".mec-event-article, .type-mec-events, .mec-wrap .event-card")
        if not cards:
            # Fallback: look for links pointing to /mc-events/
            cards = self._find_event_containers(soup)

        for card in cards:
            event = self._parse_card(card, iso_date)
            if event:
                results.append(event)

        return results

    def _find_event_containers(self, soup: BeautifulSoup) -> list[Tag]:
        """Find parent containers of mc-events links as a fallback."""
        seen: set[int] = set()
        containers: list[Tag] = []
        for link in soup.select("a[href*='/mc-events/']"):
            parent = link.find_parent(["article", "div", "li"])
            if parent and id(parent) not in seen:
                seen.add(id(parent))
                containers.append(parent)
        return containers

    def _parse_card(self, card: Tag, iso_date: str) -> Optional[Event]:
        """Extract an Event from a single event card element."""
        try:
            # Title & link — prefer an anchor pointing to /mc-events/
            link_tag = card.select_one("a[href*='/mc-events/']")
            if not link_tag:
                link_tag = card.select_one("a[href]")
            if not link_tag:
                return None

            raw_title = link_tag.get_text(strip=True)
            href = link_tag.get("href", "")
            source_url = self.absolute_url(BASE, href)

            # Split "Event Title: Venue Name" pattern
            title, venue = self._split_title_venue(raw_title)

            # Time — look for common MEC time elements or text patterns
            start_time, end_time = self._extract_times(card)

            # If no times from structured elements, try Google Calendar link
            if not start_time:
                start_time, end_time = self._extract_times_from_gcal(card)

            # Cost / labels
            description = self._extract_description(card)

            return Event(
                title=title,
                date=iso_date,
                time=start_time,
                end_time=end_time,
                venue=venue,
                description=description,
                source_url=source_url,
                source_name="Ann Arbor Observer",
                tags=["Community"],
            )
        except Exception:
            logger.exception("Failed to parse Observer event card")
            return None

    @staticmethod
    def _split_title_venue(raw_title: str) -> tuple[str, Optional[str]]:
        """Split 'Event Title: Venue Name' into (title, venue).

        If there's no colon or the colon looks like it's part of the title
        (e.g., time-like patterns), returns (raw_title, None).
        """
        if ": " in raw_title:
            parts = raw_title.split(": ", 1)
            # Heuristic: if the right side looks like a time, don't split
            if not re.match(r"^\d{1,2}:\d{2}", parts[1]):
                return parts[0].strip(), parts[1].strip()
        return raw_title.strip(), None

    def _extract_times(self, card: Tag) -> tuple[Optional[str], Optional[str]]:
        """Extract start/end times from structured MEC elements or text."""
        # MEC often uses .mec-event-time or .mec-start-time / .mec-end-time
        time_el = card.select_one(
            ".mec-event-time, .mec-time, .event-time, .mec-start-time"
        )
        if time_el:
            return self._parse_time_range(time_el.get_text(strip=True))

        # Fallback: search all text for time-like patterns
        text = card.get_text(" ", strip=True)
        return self._parse_time_range(text)

    @staticmethod
    def _parse_time_range(text: str) -> tuple[Optional[str], Optional[str]]:
        """Parse '6:00 pm - 7:00 pm' or '7:00 pm' from text."""
        match = re.search(
            r"(\d{1,2}:\d{2}\s*[ap]\.?m\.?)"
            r"(?:\s*[-–]\s*(\d{1,2}:\d{2}\s*[ap]\.?m\.?))?",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None, None

        start_raw = re.sub(r"\.", "", match.group(1))  # "p.m." -> "pm"
        start = AAObserverScraper.to_24h(start_raw)

        end = None
        if match.group(2):
            end_raw = re.sub(r"\.", "", match.group(2))
            end = AAObserverScraper.to_24h(end_raw)

        return start, end

    def _extract_times_from_gcal(self, card: Tag) -> tuple[Optional[str], Optional[str]]:
        """Try to extract times from a Google Calendar link's dates parameter."""
        gcal_link = card.select_one("a[href*='calendar.google.com']")
        if not gcal_link:
            return None, None

        href = gcal_link.get("href", "")
        match = re.search(
            r"dates=(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})\d{2}"
            r"/(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})\d{2}",
            href,
        )
        if not match:
            return None, None

        start_time = f"{match.group(4)}:{match.group(5)}"
        end_time = f"{match.group(9)}:{match.group(10)}"
        return start_time, end_time

    @staticmethod
    def _extract_description(card: Tag) -> Optional[str]:
        """Pull a short description from the card if available."""
        # Look for description/excerpt elements
        desc_el = card.select_one(
            ".mec-event-description, .event-description, .mec-event-excerpt, p"
        )
        if desc_el:
            text = desc_el.get_text(" ", strip=True)
            if text and len(text) > 10:
                return BaseScraper.truncate(text)
        return None
