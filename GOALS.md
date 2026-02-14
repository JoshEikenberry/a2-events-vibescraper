# VibeScraper — Project Goals

## Vision

A single, daily-updated Markdown document listing **every upcoming public event** across Ann Arbor, Michigan and its surrounding communities — compiled automatically by scraping dozens of independent event calendars scattered across the web.

---

## Problem Statement

Ann Arbor and its neighboring communities have a rich events scene — live music at local venues, comedy shows, library programs, city council meetings, farmers markets, art exhibitions, restaurant specials, and more. But discovering these events requires visiting many separate websites, each with its own calendar format and layout. There is no unified view.

**VibeScraper** solves this by aggregating all of these sources into one clean, readable Markdown file that is regenerated daily.

---

## Core Goals

### 1. Extensible Multi-Site Scraping

- Scrape event data (title, date/time, location, description, source URL) from a configurable list of website URLs.
- Each website gets its own **scraper module** that understands that site's structure.
- Adding a new source should be as simple as dropping in a new module — no changes to the core pipeline required.
- Target sources include (but are not limited to):
  - **Ann Arbor District Library (AADL)** events calendar
  - **University of Michigan** events
  - **The Ark**, **Blind Pig**, and other music venues
  - **Ann Arbor Comedy Showcase**
  - **Kerrytown Concert House**
  - **City of Ann Arbor** official events / city council
  - **MLive / Ann Arbor News** events listings
  - **Destination Ann Arbor** (convention & visitors bureau)
  - **Ann Arbor Observer** calendar
  - **Local restaurant and bar** event pages (live music nights, trivia, etc.)
  - **Ypsilanti**, **Dexter**, **Saline**, **Chelsea** community calendars
  - **Washtenaw County** events

### 2. Daily Automated Execution

- The program runs once per day (e.g., via cron, Task Scheduler, or a CI pipeline).
- Each run scrapes all configured sources for upcoming events — not just today's events, but anything in the future that has been posted.
- The lookahead window is **90 days** — events beyond that horizon are ignored.
- Net-new events discovered on each run are merged into the known event list.

### 3. Unified Markdown Output

- All upcoming events are compiled into a single, well-formatted Markdown file (`EVENTS.md`).
- Events are organized in a clear, readable structure (e.g., grouped by date, then sorted by time).
- Each event entry includes at minimum:
  - **Event name**
  - **Date & time**
  - **Venue / location**
  - **Short description** (if available)
  - **Source URL** (link back to the original listing)

### 4. Duplicate Detection & Cleanup

- Events that appear on multiple source sites (e.g., a concert listed on both the venue's site and MLive) should be detected as suspected duplicates.
- Duplicates are merged or deduplicated so the final output contains only one entry per real-world event.
- Deduplication should use fuzzy matching on event name, date, and venue — exact matches are not required.

### 5. Event Lifecycle Management

- A persistent data store (e.g., JSON or SQLite) tracks all known events across runs.
- On each run:
  - **New events** are added to the store.
  - **Existing events** are updated if details have changed.
  - **Past events** (date before today) are moved out of `EVENTS.md` and archived into a separate file (`ARCHIVE.md`), organized by month or date.
- This ensures the main document always reflects only **current and future** events.

### 6. Command-Line Interface

- The application is invoked from the command line.
- Supports commands/flags such as:
  - `vibescraper run` — execute a full scrape-and-publish cycle.
  - `vibescraper list-sources` — show all configured scraper sources.
  - `vibescraper add-source <url>` — register a new source (if a matching scraper module exists).
  - `vibescraper archive` — manually trigger archival of past events.
- Clear logging output so the user can see what was scraped, how many new events were found, and any errors.

---

## Non-Goals (for now)

- **Web UI or app** — output is Markdown only; no server or frontend.
- **User accounts or authentication** — this is a local tool, not a service.
- **Real-time updates** — daily batch runs are sufficient.
- **Paid or login-gated sources** — only publicly accessible calendars are scraped.

---

## Technical Constraints

- **Language**: Python 3.10+
- **Distribution**: Runnable as a CLI tool; optionally installable via `pip`.
- **Dependencies**: Minimize heavy dependencies; prefer `requests`/`httpx` + `BeautifulSoup` for scraping, with `playwright` available for JavaScript-rendered pages.
- **Storage**: Structured JSON file storage — no external database required.
- **Platform**: Must run on Windows; should also work on macOS/Linux.

---

## Development Notes — Scraper Iteration

When adding new scrapers, follow this process **every time**:

1. **Review all existing scrapers first.** Look for shared patterns, common parsing logic, or reusable helpers that have emerged. If two or more scrapers do similar work (e.g., parsing date formats, paginating, extracting structured fields), extract that into `BaseScraper` or a shared utility.
2. **Consider optimizations.** When a better approach is discovered while building a new scraper, backport it to all previously created scrapers so the codebase stays consistent.
3. **Prioritize readability and consistency.** All scrapers should follow the same structural conventions — method naming, ordering, docstrings, and error handling — so that any scraper can serve as a template for the next.

The goal is continuous refinement: each new scraper is an opportunity to improve the entire scraper layer.

---

## Success Criteria

The project is successful when a user can:

1. Run `vibescraper run` once per day.
2. Open `EVENTS.md` and see a complete, deduplicated, well-formatted list of every upcoming public event in the Ann Arbor area.
3. Add a new event source by writing a small scraper module and registering it — with no changes to the core application.
4. Trust that past events are automatically archived and no longer clutter the main document.
