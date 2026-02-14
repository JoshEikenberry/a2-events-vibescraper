"""Scraper for Kerrytown Concert House events."""

from vibescraper.scrapers.base import ScraperRegistry
from vibescraper.scrapers.tribe_events import TribeDefaults, TribeEventsListScraper


@ScraperRegistry.register
class KerrytownScraper(TribeEventsListScraper):
    """Scrapes Kerrytown Concert House events (Tribe Events Calendar)."""

    name = "kerrytown"
    base_url = "https://kerrytownconcerthouse.com/events/list/"
    tribe_defaults = TribeDefaults(
        venue="Kerrytown Concert House",
        address="415 N. 4th Ave, Ann Arbor, MI 48104",
        source_name="Kerrytown Concert House",
        tags=["Music", "Arts"],
    )
