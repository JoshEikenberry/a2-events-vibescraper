"""Scraper for The Ark music venue events."""

from vibescraper.scrapers.base import ScraperRegistry
from vibescraper.scrapers.tribe_events import TribeDefaults, TribeEventsListScraper


@ScraperRegistry.register
class TheArkScraper(TribeEventsListScraper):
    """Scrapes The Ark's upcoming events list (Tribe Events Calendar)."""

    name = "theark"
    base_url = "https://theark.org/events/list/"
    tribe_defaults = TribeDefaults(
        venue="The Ark",
        address="316 S. Main St, Ann Arbor, MI",
        source_name="The Ark",
        tags=["Live Music"],
    )
