"""Scraper for Destination Ann Arbor events (RSS feed)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

from vibescraper.models import Event, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

logger = logging.getLogger(__name__)

RSS_URL = "https://www.annarbor.org/event/rss/"
BASE = "https://www.annarbor.org"


@ScraperRegistry.register
class DestinationAAScraper(BaseScraper):
    """Scrapes Destination Ann Arbor events via the public RSS feed.

    Destination Ann Arbor (annarbor.org) is the convention and visitors
    bureau. Their events RSS feed provides structured event data
    including titles, dates, descriptions, and links.
    """

    name = "destinationaa"
    base_url = f"{BASE}/events/"

    def _scrape_impl(self) -> list[Event]:
        events: list[Event] = []
        cutoff = lookahead_cutoff()

        resp = self.fetch(RSS_URL)
        if resp is None:
            return events

        try:
            root = ElementTree.fromstring(resp.text)
        except ElementTree.ParseError:
            logger.error("Destination AA: invalid XML/RSS response")
            return events

        # RSS format: <rss><channel><item>...</item></channel></rss>
        channel = root.find("channel")
        if channel is None:
            logger.error("Destination AA: no <channel> in RSS feed")
            return events

        for item in channel.findall("item"):
            event = self._parse_item(item)
            if event and event.date <= cutoff:
                events.append(event)

        logger.info("Destination AA: scraped %d event(s)", len(events))
        return events

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_item(self, item: ElementTree.Element) -> Optional[Event]:
        """Parse a single RSS <item> into an Event."""
        try:
            title = (item.findtext("title") or "").strip()
            if not title:
                return None

            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()

            # Clean HTML from description
            description = re.sub(r"<[^>]+>", "", description).strip()
            description = self.truncate(description)

            # Date: RSS uses pubDate format "Mon, 01 Jan 2026 00:00:00 GMT"
            # or might use a custom date field
            pub_date = (item.findtext("pubDate") or "").strip()

            # Try to find event-specific date fields (Simpleview may use custom namespace)
            # Also check for ev:startdate or similar
            iso_date = None
            time_str = None

            # Check for category/georss or custom namespace elements
            for child in item:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag.lower() in ("startdate", "eventdate", "start"):
                    iso_date = self._parse_rss_date(child.text or "")
                    break

            if not iso_date and pub_date:
                iso_date = self._parse_rss_date(pub_date)

            if not iso_date:
                # Try to extract date from title or description
                iso_date = self._extract_date_from_text(title + " " + description)

            if not iso_date:
                return None

            # Try to extract venue from description or category
            venue = None
            category = item.findtext("category")
            if category:
                venue = category.strip()

            # Extract location from description if it mentions known venues
            if not venue:
                venue = self._extract_venue(description)

            return Event(
                title=title,
                date=iso_date,
                time=time_str,
                venue=venue or "Ann Arbor Area",
                description=description or None,
                source_url=link,
                source_name="Destination Ann Arbor",
                tags=["Community"],
            )
        except Exception:
            logger.exception("Failed to parse Destination AA RSS item")
            return None

    def _parse_rss_date(self, date_str: str) -> Optional[str]:
        """Parse various RSS date formats into ISO date."""
        date_str = date_str.strip()
        formats = [
            "%a, %d %b %Y %H:%M:%S %Z",  # RFC 822: "Mon, 01 Jan 2026 00:00:00 GMT"
            "%a, %d %b %Y %H:%M:%S %z",  # with timezone offset
            "%Y-%m-%dT%H:%M:%S",  # ISO 8601
            "%Y-%m-%d",  # plain ISO date
            "%m/%d/%Y",  # US format
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Try isoformat parsing
        try:
            return (
                datetime.fromisoformat(date_str.replace("Z", "+00:00")).strftime(
                    "%Y-%m-%d"
                )
            )
        except ValueError:
            pass

        return None

    def _extract_date_from_text(self, text: str) -> Optional[str]:
        """Try to extract a date from free text."""
        months = (
            "January|February|March|April|May|June|July|August|"
            "September|October|November|December"
        )
        match = re.search(
            rf"({months})\s+(\d{{1,2}}),?\s+(\d{{4}})",
            text,
            re.IGNORECASE,
        )
        if match:
            return self.parse_date_mdy(
                f"{match.group(1)} {match.group(2)}, {match.group(3)}"
            )
        return None

    @staticmethod
    def _extract_venue(text: str) -> Optional[str]:
        """Try to extract a venue name from description text."""
        # Common patterns: "at [Venue Name]" or "Location: [Venue]"
        match = re.search(r"(?:at|@|Location:\s*)([A-Z][^,.]{5,40})", text)
        if match:
            return match.group(1).strip()
        return None
