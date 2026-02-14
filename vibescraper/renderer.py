"""Render events to well-formatted Markdown files."""

from __future__ import annotations

import logging
from datetime import datetime
from itertools import groupby
from pathlib import Path

from vibescraper.models import Event

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("output")


def _format_date_heading(iso_date: str) -> str:
    """Convert '2026-02-15' to 'Saturday, February 15, 2026'."""
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return dt.strftime("%A, %B %d, %Y").replace(" 0", " ")


def _format_time(time_24: str) -> str:
    """Convert '19:30' to '7:30 PM'."""
    dt = datetime.strptime(time_24, "%H:%M")
    return dt.strftime("%I:%M %p").lstrip("0")


def _format_time_range(event: Event) -> str:
    """Build a human-readable time string for an event."""
    if not event.time:
        return "All day"
    start = _format_time(event.time)
    if event.end_time:
        return f"{start} - {_format_time(event.end_time)}"
    return start


def _format_month_heading(iso_date: str) -> str:
    """Convert '2026-02-15' to 'February 2026'."""
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return dt.strftime("%B %Y")


# ------------------------------------------------------------------
# Event entry
# ------------------------------------------------------------------

def _render_event(event: Event) -> str:
    """Render a single event as a Markdown block."""
    lines: list[str] = []

    # Title (as h3)
    lines.append(f"### {event.title}")
    lines.append("")

    # Details list
    lines.append(f"- **Time:** {_format_time_range(event)}")

    if event.venue:
        lines.append(f"- **Venue:** {event.venue}")

    if event.address:
        lines.append(f"- **Address:** {event.address}")

    if event.description:
        lines.append(f"- **Description:** {event.description}")

    if event.tags:
        lines.append(f"- **Tags:** {', '.join(event.tags)}")

    if event.source_url and event.source_name:
        lines.append(f"- **Source:** [{event.source_name}]({event.source_url})")
    elif event.source_url:
        lines.append(f"- **Source:** [Link]({event.source_url})")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Full document renderers
# ------------------------------------------------------------------

def render_events(events: list[Event]) -> str:
    """Render the main upcoming-events Markdown document.

    Events are grouped by date, sorted chronologically within each day.
    """
    now = datetime.now()
    lines: list[str] = [
        "# Upcoming Events -- Ann Arbor Area",
        "",
        f"*Last updated: {now.strftime('%B %d, %Y at %I:%M %p').replace(' 0', ' ')}*",
        "",
        f"*{len(events)} event(s) from {_count_sources(events)} source(s)*",
        "",
        "---",
        "",
    ]

    if not events:
        lines.append("*No upcoming events found.*")
        return "\n".join(lines)

    sorted_events = sorted(events, key=lambda e: e.sort_key)

    for date_str, day_events in groupby(sorted_events, key=lambda e: e.date):
        day_list = list(day_events)
        heading = _format_date_heading(date_str)
        lines.append(f"## {heading}")
        lines.append("")

        for event in day_list:
            lines.append(_render_event(event))
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def render_archive(events: list[Event]) -> str:
    """Render the archive Markdown document.

    Events are grouped by month, then by date within each month.
    """
    now = datetime.now()
    lines: list[str] = [
        "# Archived Events -- Ann Arbor Area",
        "",
        f"*Last updated: {now.strftime('%B %d, %Y at %I:%M %p').replace(' 0', ' ')}*",
        "",
        f"*{len(events)} archived event(s)*",
        "",
        "---",
        "",
    ]

    if not events:
        lines.append("*No archived events.*")
        return "\n".join(lines)

    sorted_events = sorted(events, key=lambda e: e.sort_key)

    # Group by month (YYYY-MM)
    for month_key, month_events in groupby(sorted_events, key=lambda e: e.date[:7]):
        month_list = list(month_events)
        month_heading = _format_month_heading(month_list[0].date)
        lines.append(f"## {month_heading}")
        lines.append("")

        # Sub-group by date
        for date_str, day_events in groupby(month_list, key=lambda e: e.date):
            day_list = list(day_events)
            heading = _format_date_heading(date_str)
            lines.append(f"### {heading}")
            lines.append("")

            for event in day_list:
                # Use h4 inside archive to avoid collision with month/date headings
                block = _render_event(event).replace("### ", "#### ", 1)
                lines.append(block)
                lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# File writers
# ------------------------------------------------------------------

def publish(
    events: list[Event],
    archive: list[Event],
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write EVENTS.md and ARCHIVE.md to the output directory.

    Returns:
        Tuple of (events_path, archive_path).
    """
    out = output_dir or DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    events_path = out / "EVENTS.md"
    archive_path = out / "ARCHIVE.md"

    events_md = render_events(events)
    events_path.write_text(events_md, encoding="utf-8")
    logger.info("Wrote %s (%d events)", events_path, len(events))

    archive_md = render_archive(archive)
    archive_path.write_text(archive_md, encoding="utf-8")
    logger.info("Wrote %s (%d events)", archive_path, len(archive))

    return events_path, archive_path


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _count_sources(events: list[Event]) -> int:
    """Count distinct source names."""
    return len({e.source_name for e in events if e.source_name})
