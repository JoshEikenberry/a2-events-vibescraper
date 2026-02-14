"""Scraper package — drop-in modules for each event source."""

from vibescraper.scrapers.base import BaseScraper, ScraperRegistry

__all__ = ["BaseScraper", "ScraperRegistry"]
