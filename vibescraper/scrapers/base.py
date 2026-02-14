"""Base scraper class and auto-discovery registry."""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from typing import ClassVar
from urllib.parse import urljoin

import httpx

from vibescraper.models import Event

logger = logging.getLogger(__name__)

DEFAULT_DELAY = 0.75  # seconds between requests
MAX_BACKOFF_MULTIPLIER = 4  # max multiplier on delay after errors (0.75 -> 3s)
MAX_CONSECUTIVE_ERRORS = 3  # skip remaining requests after this many errors in a row


class ScraperRegistry:
    """Central registry of all available scrapers."""

    _scrapers: ClassVar[dict[str, type[BaseScraper]]] = {}

    @classmethod
    def register(cls, scraper_cls: type[BaseScraper]) -> type[BaseScraper]:
        """Register a scraper class. Used as a decorator."""
        name = scraper_cls.name
        if not name:
            raise ValueError(f"{scraper_cls.__name__} must define a 'name' attribute.")
        cls._scrapers[name] = scraper_cls
        logger.debug("Registered scraper: %s", name)
        return scraper_cls

    @classmethod
    def get(cls, name: str) -> type[BaseScraper] | None:
        """Look up a scraper by name."""
        return cls._scrapers.get(name)

    @classmethod
    def all(cls) -> dict[str, type[BaseScraper]]:
        """Return all registered scrapers."""
        return dict(cls._scrapers)

    @classmethod
    def clear(cls) -> None:
        """Remove all registrations (useful for testing)."""
        cls._scrapers.clear()


class BaseScraper(ABC):
    """Abstract base class every scraper module must implement.

    Provides shared utilities and an HTTP ``fetch()`` helper that automatically:
    - Waits ``request_delay`` seconds between requests (default 0.75s).
    - Backs off (doubles the delay) when the server returns 4xx/5xx.
    - Aborts the session after ``MAX_CONSECUTIVE_ERRORS`` failures in a row.

    The ``scrape()`` method handles resource cleanup (closing the HTTP client)
    via a template-method pattern — subclasses implement ``_scrape_impl()``.

    To create a new scraper:

        1. Create a file in vibescraper/scrapers/ (e.g., aadl.py).
        2. Subclass BaseScraper.
        3. Set ``name`` and ``base_url``.
        4. Implement ``_scrape_impl()``.
        5. Decorate the class with ``@ScraperRegistry.register``.

    Example::

        @ScraperRegistry.register
        class AADLScraper(BaseScraper):
            name = "aadl"
            base_url = "https://aadl.org/events"

            def _scrape_impl(self) -> list[Event]:
                resp = self.fetch("https://aadl.org/events-feed/upcoming?page=0")
                ...
    """

    name: ClassVar[str] = ""
    base_url: ClassVar[str] = ""
    request_delay: ClassVar[float] = DEFAULT_DELAY

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=20, follow_redirects=True)
        self._current_delay = self.request_delay
        self._consecutive_errors = 0
        self._request_count = 0
        self._aborted = False

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    @staticmethod
    def to_24h(time_str: str) -> str:
        """Convert '7:00pm' or '7:00 pm' -> '19:00'."""
        time_str = time_str.strip().lower().replace(" ", "")
        dt = datetime.strptime(time_str, "%I:%M%p")
        return dt.strftime("%H:%M")

    @staticmethod
    def split_br(tag: "Tag") -> list[str]:
        """Split a BeautifulSoup tag's contents by <br/> into text segments."""
        from bs4 import Tag as BsTag
        parts: list[str] = []
        current: list[str] = []
        for child in tag.children:
            if isinstance(child, BsTag) and child.name == "br":
                parts.append(" ".join(current).strip())
                current = []
            else:
                text = child.get_text() if isinstance(child, BsTag) else str(child)
                text = text.strip()
                if text:
                    current.append(text)
        if current:
            parts.append(" ".join(current).strip())
        return [p for p in parts if p]

    @staticmethod
    def parse_date_mdy(text: str) -> str | None:
        """Parse 'February 12, 2026' or 'Feb 12, 2026' into ISO date '2026-02-12'.

        Returns None if parsing fails.
        """
        text = re.sub(r"\s+", " ", text).strip()
        # Normalize comma placement: "February 12 2026" -> "February 12, 2026"
        text = re.sub(r"(\d)(,?\s+)(\d{4})", r"\1, \3", text)
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    @staticmethod
    def truncate(text: str | None, max_len: int = 200) -> str | None:
        """Truncate text to *max_len* characters, appending '...' if trimmed.

        Returns None for empty/None input.
        """
        if not text:
            return None
        text = " ".join(text.split())  # normalize whitespace
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    @staticmethod
    def absolute_url(base: str, href: str) -> str:
        """Join *href* against *base* to produce a full URL."""
        return urljoin(base, href or "")

    @staticmethod
    def parse_iso_datetime(value: str) -> datetime | None:
        """Parse an ISO-8601 datetime string (with or without timezone).

        Returns None on failure.
        """
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def iter_jsonld(soup: "BeautifulSoup") -> Iterator[dict]:
        """Yield every JSON-LD object found in ``<script>`` tags.

        Handles single objects, lists, and ``@graph`` arrays.
        """
        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or ""
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            stack = data if isinstance(data, list) else [data]
            for item in stack:
                if not isinstance(item, dict):
                    continue
                graph = item.get("@graph")
                if isinstance(graph, list):
                    for g in graph:
                        if isinstance(g, dict):
                            yield g
                yield item

    @classmethod
    def iter_jsonld_of_type(cls, soup: "BeautifulSoup", type_name: str) -> Iterator[dict]:
        """Yield JSON-LD objects whose ``@type`` matches *type_name*."""
        for item in cls.iter_jsonld(soup):
            t = item.get("@type")
            if t == type_name or (isinstance(t, list) and type_name in t):
                yield item

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def fetch(self, url: str) -> httpx.Response | None:
        """Fetch a URL with polite delay and automatic backoff.

        Returns:
            The ``httpx.Response`` on success, or ``None`` if the request
            failed and should be skipped.
        """
        if self._aborted:
            return None

        # Polite delay (skip before the very first request)
        if self._request_count > 0:
            time.sleep(self._current_delay)
        self._request_count += 1

        try:
            logger.debug("Fetching %s (delay=%.2fs)", url, self._current_delay)
            resp = self._client.get(url)

            if resp.status_code >= 400:
                self._handle_error(url, status=resp.status_code)
                return None

            # Success — reset backoff
            if self._current_delay != self.request_delay:
                logger.debug("Request succeeded, resetting delay to %.2fs", self.request_delay)
            self._current_delay = self.request_delay
            self._consecutive_errors = 0
            return resp

        except httpx.HTTPError as exc:
            self._handle_error(url, exc=exc)
            return None

    def _handle_error(
        self,
        url: str,
        *,
        status: int | None = None,
        exc: Exception | None = None,
    ) -> None:
        """Log the error, increase backoff, and maybe abort the session."""
        self._consecutive_errors += 1

        reason = f"HTTP {status}" if status else str(exc)
        logger.warning(
            "%s: request failed for %s (%s) [%d/%d consecutive errors]",
            self.name,
            url,
            reason,
            self._consecutive_errors,
            MAX_CONSECUTIVE_ERRORS,
        )

        if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            logger.error(
                "%s: %d consecutive errors — aborting remaining requests.",
                self.name,
                self._consecutive_errors,
            )
            self._aborted = True
            return

        # Double the delay, up to the max multiplier
        new_delay = min(
            self._current_delay * 2,
            self.request_delay * MAX_BACKOFF_MULTIPLIER,
        )
        logger.info("%s: backing off — next delay %.2fs", self.name, new_delay)
        self._current_delay = new_delay

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    @property
    def aborted(self) -> bool:
        """Whether this session was aborted due to repeated errors."""
        return self._aborted

    def scrape(self) -> list[Event]:
        """Fetch and parse events from this source.

        Handles resource cleanup automatically — subclasses should
        implement ``_scrape_impl()`` instead of overriding this method.
        """
        try:
            return self._scrape_impl()
        finally:
            self.close()

    @abstractmethod
    def _scrape_impl(self) -> list[Event]:
        """Subclass hook: fetch and parse events.

        Returns:
            A list of Event objects.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
