"""Scraper for Chelsea Area Chamber of Commerce events."""

from vibescraper.scrapers.base import ScraperRegistry
from vibescraper.scrapers.tribe_events import TribeDefaults, TribeEventsListScraper


@ScraperRegistry.register
class ChelseaScraper(TribeEventsListScraper):
    """Scrapes Chelsea community events (Tribe Events Calendar)."""

    name = "chelsea"
    base_url = "https://chelseamich.com/events/list/"
    tribe_defaults = TribeDefaults(
        venue="Chelsea",
        address="Chelsea, MI 48118",
        source_name="Chelsea Chamber",
        tags=["Community"],
    )
