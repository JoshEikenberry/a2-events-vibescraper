"""Command-line interface for VibeScraper."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

import click

import vibescraper.scrapers as scrapers_pkg
from vibescraper.renderer import publish
from vibescraper.scrapers import ScraperRegistry
from vibescraper.store import EventStore

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format=LOG_FORMAT, level=level)


# ---------------------------------------------------------------------------
# Auto-discover scraper modules
# ---------------------------------------------------------------------------

def _discover_scrapers() -> None:
    """Import every module in vibescraper.scrapers so @register decorators fire."""
    for _importer, modname, _ispkg in pkgutil.iter_modules(scrapers_pkg.__path__):
        if modname == "base":
            continue
        importlib.import_module(f"vibescraper.scrapers.{modname}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for JSON data files (default: ./data).",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for Markdown output (default: ./output).",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, data_dir: Path | None, output_dir: Path | None) -> None:
    """VibeScraper — Ann Arbor event aggregator."""
    _setup_logging(verbose)
    _discover_scrapers()
    ctx.ensure_object(dict)
    ctx.obj["store"] = EventStore(data_dir=data_dir)
    ctx.obj["output_dir"] = output_dir


@cli.command()
@click.pass_context
def run(ctx: click.Context) -> None:
    """Execute a full scrape-and-publish cycle."""
    store: EventStore = ctx.obj["store"]
    all_scrapers = ScraperRegistry.all()

    if not all_scrapers:
        click.echo("No scrapers registered. Add scraper modules to vibescraper/scrapers/.")
        return

    click.echo(f"Running {len(all_scrapers)} scraper(s)...\n")

    total_added = 0
    total_updated = 0

    for name, scraper_cls in all_scrapers.items():
        click.echo(f"  > {name} ({scraper_cls.base_url})")
        try:
            scraper = scraper_cls()
            events = scraper.scrape()
            added, updated = store.upsert_events(events)
            total_added += added
            total_updated += updated
            click.echo(f"    found {len(events)} event(s): {added} new, {updated} updated")
        except Exception as exc:
            click.echo(f"    ERROR: {exc}", err=True)

    archived = store.archive_past_events()

    click.echo(f"\nDone. +{total_added} new, ~{total_updated} updated, {archived} archived.")
    s = store.stats()
    click.echo(f"Store: {s['current_events']} current, {s['archived_events']} archived.")

    # Publish Markdown & HTML
    output_dir = ctx.obj["output_dir"]
    events_path, archive_path, calendar_path = publish(
        store.load_events(), store.load_archive(), output_dir=output_dir
    )
    click.echo(f"\nPublished: {events_path}")
    click.echo(f"Published: {archive_path}")
    click.echo(f"Published: {calendar_path}")


@cli.command("list-sources")
def list_sources() -> None:
    """Show all registered scraper sources."""
    all_scrapers = ScraperRegistry.all()
    if not all_scrapers:
        click.echo("No scrapers registered.")
        return

    click.echo(f"{'Name':<20} {'URL'}")
    click.echo(f"{'-' * 20} {'-' * 50}")
    for name, cls in sorted(all_scrapers.items()):
        click.echo(f"{name:<20} {cls.base_url}")


@cli.command("publish")
@click.pass_context
def publish_cmd(ctx: click.Context) -> None:
    """Regenerate EVENTS.md, ARCHIVE.md, and calendar.html from the store (no scraping)."""
    store: EventStore = ctx.obj["store"]
    output_dir = ctx.obj["output_dir"]
    events_path, archive_path, calendar_path = publish(
        store.load_events(), store.load_archive(), output_dir=output_dir
    )
    s = store.stats()
    click.echo(f"Published: {events_path} ({s['current_events']} events)")
    click.echo(f"Published: {archive_path} ({s['archived_events']} archived)")
    click.echo(f"Published: {calendar_path} ({s['current_events']} events)")


@cli.command()
@click.pass_context
def archive(ctx: click.Context) -> None:
    """Manually archive past events and republish Markdown & HTML."""
    store: EventStore = ctx.obj["store"]
    count = store.archive_past_events()
    click.echo(f"Archived {count} event(s).")

    output_dir = ctx.obj["output_dir"]
    events_path, archive_path, calendar_path = publish(
        store.load_events(), store.load_archive(), output_dir=output_dir
    )
    s = store.stats()
    click.echo(f"Published: {events_path} ({s['current_events']} events)")
    click.echo(f"Published: {archive_path} ({s['archived_events']} archived)")
    click.echo(f"Published: {calendar_path} ({s['current_events']} events)")


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show store statistics."""
    store: EventStore = ctx.obj["store"]
    s = store.stats()
    click.echo(f"Current events:  {s['current_events']}")
    click.echo(f"Archived events: {s['archived_events']}")
