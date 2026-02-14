"""Base scraper for WordPress sites using The Events Calendar (Tribe) plugin."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Optional

from bs4 import BeautifulSoup, Tag

from vibescraper.models import Event, lookahead_cutoff
from vibescraper.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TribeDefaults:
    """Venue/source constants for a Tribe Events Calendar site."""

    venue: str
    address: str
    source_name: str
    tags: list[str] = field(default_factory=list)


class TribeEventsListScraper(BaseScraper):
    """Base for WordPress sites using the Tribe Events Calendar list view.

    Subclasses only need to set ``name``, ``base_url`` (ending in
    ``/events/list/``), and ``tribe_defaults``.
    """

    tribe_defaults: ClassVar[TribeDefaults]
    max_pages: ClassVar[int] = 10

    # ------------------------------------------------------------------
    # Scraping
    # ------------------------------------------------------------------

    def _scrape_impl(self) -> list[Event]:
        events: list[Event] = []
        cutoff = lookahead_cutoff()
        page = 1
        hit_cutoff = False

        while page <= self.max_pages:
            url = self.base_url if page == 1 else f"{self.base_url}page/{page}/"
            resp = self.fetch(url)

            if resp is None:
                break

            soup = BeautifulSoup(resp.text, "html.parser")

            # JSON-LD first, fall back to HTML
            page_events = self._parse_jsonld(soup) or self._parse_html(soup)

            if not page_events:
                break

            for event in page_events:
                if event.date > cutoff:
                    hit_cutoff = True
                    continue
                events.append(event)

            if hit_cutoff or not self._has_next_page(soup):
                break

            page += 1

        logger.info("%s: scraped %d event(s) across %d page(s)", self.name, len(events), page)
        return events

    # ------------------------------------------------------------------
    # JSON-LD parsing (preferred)
    # ------------------------------------------------------------------

    def _parse_jsonld(self, soup: BeautifulSoup) -> list[Event]:
        events: list[Event] = []
        for item in self.iter_jsonld_of_type(soup, "Event"):
            event = self._jsonld_to_event(item)
            if event:
                events.append(event)
        return events

    def _jsonld_to_event(self, data: dict) -> Optional[Event]:
        try:
            title = (data.get("name") or "").strip()
            if not title:
                return None

            start = data.get("startDate") or ""
            if not start:
                return None

            dt = self.parse_iso_datetime(start)
            if not dt:
                return None
            iso_date = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M") if "T" in start else None

            end_time = None
            end = data.get("endDate") or ""
            if end and "T" in end:
                end_dt = self.parse_iso_datetime(end)
                if end_dt and end_dt.strftime("%Y-%m-%d") == iso_date:
                    end_time = end_dt.strftime("%H:%M")

            venue = None
            address = None
            location = data.get("location", {})
            if isinstance(location, dict):
                venue = location.get("name") or self.tribe_defaults.venue
                addr = location.get("address", {})
                if isinstance(addr, dict):
                    parts = [
                        addr.get("streetAddress", ""),
                        addr.get("addressLocality", ""),
                        addr.get("addressRegion", ""),
                    ]
                    address = ", ".join(p for p in parts if p) or None

            description = self.truncate((data.get("description") or "").strip())
            source_url = data.get("url") or ""

            return Event(
                title=title,
                date=iso_date,
                time=time_str,
                end_time=end_time,
                venue=venue or self.tribe_defaults.venue,
                address=address or self.tribe_defaults.address,
                description=description,
                source_url=source_url,
                source_name=self.tribe_defaults.source_name,
                tags=list(self.tribe_defaults.tags),
            )
        except Exception:
            logger.exception("%s: failed to parse JSON-LD event", self.name)
            return None

    # ------------------------------------------------------------------
    # HTML fallback parsing
    # ------------------------------------------------------------------

    def _parse_html(self, soup: BeautifulSoup) -> list[Event]:
        events: list[Event] = []
        articles = (
            soup.select("article.tribe-events-calendar-list__event")
            or soup.select(".tribe_events .type-tribe_events")
            or soup.select("article[class*='tribe_events']")
        )
        for article in articles:
            event = self._parse_article(article)
            if event:
                events.append(event)
        return events

    def _parse_article(self, article: Tag) -> Optional[Event]:
        try:
            title_el = (
                article.select_one(".tribe-events-calendar-list__event-title a")
                or article.select_one("h2 a")
                or article.select_one("h3 a")
                or article.select_one(".tribe-event-url a")
            )
            if not title_el:
                return None

            title = title_el.get_text(strip=True)
            href = title_el.get("href", "") or ""
            base = re.match(r"https?://[^/]+", self.base_url)
            site_base = base.group(0) if base else self.base_url
            source_url = self.absolute_url(site_base, href)

            time_el = article.select_one("time[datetime]")
            if time_el:
                dt = self.parse_iso_datetime(time_el.get("datetime", "") or "")
                if dt:
                    iso_date = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")
                else:
                    iso_date, time_str = self._parse_date_text(article)
            else:
                iso_date, time_str = self._parse_date_text(article)

            if not iso_date:
                return None

            desc_el = (
                article.select_one(".tribe-events-calendar-list__event-description p")
                or article.select_one(".tribe-events-content p")
            )
            description = self.truncate(desc_el.get_text(strip=True) if desc_el else None)

            return Event(
                title=title,
                date=iso_date,
                time=time_str,
                venue=self.tribe_defaults.venue,
                address=self.tribe_defaults.address,
                description=description,
                source_url=source_url,
                source_name=self.tribe_defaults.source_name,
                tags=list(self.tribe_defaults.tags),
            )
        except Exception:
            logger.exception("%s: failed to parse Tribe event article", self.name)
            return None

    def _parse_date_text(self, article: Tag) -> tuple[Optional[str], Optional[str]]:
        schedule = (
            article.select_one(".tribe-event-schedule-details")
            or article.select_one("abbr.tribe-events-abbr")
        )
        if not schedule:
            return None, None

        text = schedule.get_text(strip=True)
        match = re.match(
            r"(\w+ \d{1,2},?\s*\d{0,4})\s*@\s*(\d{1,2}:\d{2}\s*(?:am|pm))",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None, None

        date_part = match.group(1).strip()
        if not re.search(r"\d{4}", date_part):
            date_part += f", {datetime.now().year}"

        iso_date = self.parse_date_mdy(date_part)
        time_str = self.to_24h(match.group(2))
        return iso_date, time_str

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    @staticmethod
    def _has_next_page(soup: BeautifulSoup) -> bool:
        next_link = (
            soup.select_one("a.tribe-events-c-nav__next")
            or soup.select_one('a[rel="next"]')
            or soup.find("a", string=re.compile(r"next\s+events", re.IGNORECASE))
        )
        return next_link is not None
