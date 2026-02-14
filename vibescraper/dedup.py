"""Fuzzy duplicate detection and merging for events."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from itertools import groupby

from vibescraper.models import Event

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Thresholds
# ------------------------------------------------------------------

TITLE_THRESHOLD = 0.80  # titles must be >= 80% similar
VENUE_THRESHOLD = 0.60  # venues must be >= 60% similar (more variation expected)
TIME_TOLERANCE_MINUTES = 30  # start times within 30 min count as close enough


# ------------------------------------------------------------------
# Normalization
# ------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)  # remove punctuation
    text = re.sub(r"\s+", " ", text)  # collapse whitespace
    return text


def _sequence_similarity(a: str, b: str) -> float:
    """Standard SequenceMatcher ratio on normalized strings."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _token_similarity(a: str, b: str) -> float:
    """Token-overlap similarity (handles word reordering).

    Computes: 2 * |intersection| / (|tokens_a| + |tokens_b|)
    """
    tokens_a = set(_normalize(a).split())
    tokens_b = set(_normalize(b).split())
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = tokens_a & tokens_b
    return 2 * len(overlap) / (len(tokens_a) + len(tokens_b))


def _similarity(a: str | None, b: str | None) -> float:
    """Return 0.0-1.0 similarity using the best of sequence and token matching.

    Returns 1.0 if both are None/empty (no data to disagree on).
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return max(_sequence_similarity(a, b), _token_similarity(a, b))


def _time_to_minutes(t: str | None) -> int | None:
    """Convert '19:30' to total minutes (1170). Returns None if missing."""
    if not t:
        return None
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _times_close(a: str | None, b: str | None) -> bool:
    """Return True if start times are within TIME_TOLERANCE_MINUTES or either is missing."""
    ma, mb = _time_to_minutes(a), _time_to_minutes(b)
    if ma is None or mb is None:
        return True  # can't disprove — assume compatible
    return abs(ma - mb) <= TIME_TOLERANCE_MINUTES


# ------------------------------------------------------------------
# Duplicate detection
# ------------------------------------------------------------------

def is_duplicate(a: Event, b: Event) -> bool:
    """Determine whether two events on the same date are likely the same event.

    Checks:
        1. Same date (caller should pre-filter).
        2. Title similarity >= TITLE_THRESHOLD.
        3. Venue similarity >= VENUE_THRESHOLD (if both have venues).
        4. Start times within TIME_TOLERANCE_MINUTES (if both have times).
    """
    if a.date != b.date:
        return False

    title_sim = _similarity(a.title, b.title)
    if title_sim < TITLE_THRESHOLD:
        return False

    venue_sim = _similarity(a.venue, b.venue)
    if a.venue and b.venue and venue_sim < VENUE_THRESHOLD:
        return False

    if not _times_close(a.time, b.time):
        return False

    logger.debug(
        "Duplicate detected (title=%.0f%%, venue=%.0f%%): %r <-> %r",
        title_sim * 100,
        venue_sim * 100,
        a.title,
        b.title,
    )
    return True


# ------------------------------------------------------------------
# Merging
# ------------------------------------------------------------------

def _field_richness(event: Event) -> int:
    """Score how many fields are populated — higher is richer."""
    score = 0
    if event.time:
        score += 1
    if event.end_time:
        score += 1
    if event.venue:
        score += 1
    if event.address:
        score += 1
    if event.description:
        score += 1
    if event.source_url:
        score += 1
    if event.tags:
        score += len(event.tags)
    return score


def _merge_pair(a: Event, b: Event) -> Event:
    """Merge two duplicate events, keeping the richest data.

    The event with more populated fields is used as the base.
    Missing fields are filled in from the other event.
    Tags and source info are combined.
    """
    # Use the richer event as the primary
    if _field_richness(b) > _field_richness(a):
        primary, secondary = b, a
    else:
        primary, secondary = a, b

    return Event(
        title=primary.title,
        date=primary.date,
        time=primary.time or secondary.time,
        end_time=primary.end_time or secondary.end_time,
        venue=primary.venue or secondary.venue,
        address=primary.address or secondary.address,
        description=_merge_descriptions(primary.description, secondary.description),
        source_url=primary.source_url,
        source_name=_merge_source_names(primary.source_name, secondary.source_name),
        tags=_merge_tags(primary.tags, secondary.tags),
    )


def _merge_descriptions(a: str | None, b: str | None) -> str | None:
    """Keep the longer description, or combine if both are short and different."""
    if not a:
        return b
    if not b:
        return a
    if _similarity(a, b) > 0.8:
        return a if len(a) >= len(b) else b
    # Both exist and are meaningfully different — keep the longer one
    return a if len(a) >= len(b) else b


def _merge_source_names(a: str | None, b: str | None) -> str | None:
    """Combine source names like 'AADL' + 'MLive' -> 'AADL, MLive'."""
    if not a:
        return b
    if not b:
        return a
    if a == b:
        return a
    return f"{a}, {b}"


def _merge_tags(a: list[str], b: list[str]) -> list[str]:
    """Union of tags, preserving order."""
    seen: set[str] = set()
    merged: list[str] = []
    for tag in a + b:
        lower = tag.lower()
        if lower not in seen:
            seen.add(lower)
            merged.append(tag)
    return merged


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def deduplicate(events: list[Event]) -> tuple[list[Event], int]:
    """Remove fuzzy duplicates from a list of events.

    Groups events by date, then compares all pairs within each day.
    When duplicates are found they are merged into a single event.

    Returns:
        (deduplicated_events, number_of_duplicates_removed)
    """
    if not events:
        return [], 0

    sorted_events = sorted(events, key=lambda e: e.sort_key)
    result: list[Event] = []
    total_removed = 0

    for _date, day_iter in groupby(sorted_events, key=lambda e: e.date):
        day_events = list(day_iter)
        merged_day, removed = _deduplicate_day(day_events)
        result.extend(merged_day)
        total_removed += removed

    if total_removed:
        logger.info("Deduplication removed %d event(s).", total_removed)
    else:
        logger.debug("No duplicates found.")

    return result, total_removed


def _deduplicate_day(events: list[Event]) -> tuple[list[Event], int]:
    """Deduplicate events within a single day.

    Uses a simple greedy approach: iterate through events and merge each
    new event into the first existing cluster it matches.
    """
    clusters: list[Event] = []
    removed = 0

    for event in events:
        merged = False
        for i, existing in enumerate(clusters):
            if is_duplicate(existing, event):
                clusters[i] = _merge_pair(existing, event)
                removed += 1
                merged = True
                break
        if not merged:
            clusters.append(event)

    return clusters, removed
