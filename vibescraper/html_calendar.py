"""Render events as an interactive HTML calendar."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from itertools import groupby

from vibescraper.models import Event

logger = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    """Basic HTML escape."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _format_time_range(event: Event) -> str:
    """Build a human-readable time string for an event."""
    if not event.time:
        return "All day"
    try:
        dt = datetime.strptime(event.time, "%H:%M")
        start = dt.strftime("%I:%M %p").lstrip("0")
        if event.end_time:
            dt_end = datetime.strptime(event.end_time, "%H:%M")
            end = dt_end.strftime("%I:%M %p").lstrip("0")
            return f"{start} - {end}"
        return start
    except ValueError:
        return "All day"


def _get_month_dates(year: int, month: int) -> tuple[list[int], datetime]:
    """Get calendar grid and first day of month."""
    first_day = datetime(year, month, 1)
    # Start of week is Monday (0)
    start_weekday = first_day.weekday()
    
    # Get last day of month
    if month == 12:
        last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = datetime(year, month + 1, 1) - timedelta(days=1)
    
    days_in_month = last_day.day
    
    # Build grid: pad with 0s for days before month starts
    grid = [0] * start_weekday + list(range(1, days_in_month + 1))
    
    return grid, first_day


def _render_event_card(event: Event) -> str:
    """Render a single event card for the calendar."""
    time_str = _format_time_range(event)
    venue = _escape_html(event.venue or "")
    title = _escape_html(event.title)
    desc = _escape_html(event.description or "")[:150]
    
    return f'''
        <div class="event-card">
            <div class="event-time">{time_str}</div>
            <div class="event-title">{title}</div>
            <div class="event-venue">{venue}</div>
            <div class="event-desc">{desc}{"..." if len(event.description or "") > 150 else ""}</div>
        </div>
'''


def render_calendar_html(events: list[Event]) -> str:
    """Render an interactive monthly calendar in HTML."""
    
    # Group events by date
    events_by_date: dict[str, list[Event]] = {}
    for event in events:
        if event.date not in events_by_date:
            events_by_date[event.date] = []
        events_by_date[event.date].append(event)
    
    # Sort events within each day
    for date in events_by_date:
        events_by_date[date].sort(key=lambda e: (e.time or "23:59", e.title))
    
    # Get range of months to display
    if not events:
        min_month = datetime.now()
        max_month = datetime.now()
    else:
        sorted_events = sorted(events, key=lambda e: e.date)
        min_date = datetime.strptime(sorted_events[0].date, "%Y-%m-%d")
        max_date = datetime.strptime(sorted_events[-1].date, "%Y-%m-%d")
        min_month = min_date.replace(day=1)
        max_month = max_date.replace(day=1)
    
    html_parts: list[str] = []
    
    # HTML header
    html_parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ann Arbor Events Calendar</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            color: white;
            margin-bottom: 40px;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .header p {
            font-size: 1.1em;
            opacity: 0.9;
        }
        
        .calendar-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        
        .month-container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            overflow: hidden;
        }
        
        .month-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
            font-size: 1.5em;
            font-weight: 600;
        }
        
        .weekday-header {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 1px;
            background: #e0e0e0;
            padding: 1px;
        }
        
        .weekday {
            background: #f5f5f5;
            padding: 10px;
            text-align: center;
            font-weight: 600;
            font-size: 0.9em;
            color: #666;
        }
        
        .day-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 1px;
            background: #e0e0e0;
            padding: 1px;
        }
        
        .day-cell {
            background: white;
            min-height: 100px;
            padding: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
        }
        
        .day-cell:hover {
            background: #f0f8ff;
        }
        
        .day-cell.has-events {
            background: #f0f7ff;
            border-left: 4px solid #667eea;
        }
        
        .day-cell.has-events:hover {
            background: #e8f2ff;
            transform: translateY(-2px);
        }
        
        .day-cell.empty {
            background: #fafafa;
        }
        
        .day-number {
            font-weight: 600;
            font-size: 1.1em;
            margin-bottom: 4px;
            color: #333;
        }
        
        .event-count {
            font-size: 0.75em;
            color: #667eea;
            font-weight: 600;
        }
        
        .events-panel {
            position: fixed;
            top: 0;
            right: -500px;
            width: 500px;
            height: 100vh;
            background: white;
            box-shadow: -5px 0 20px rgba(0,0,0,0.2);
            z-index: 1000;
            display: flex;
            flex-direction: column;
            transition: right 0.3s ease;
            overflow: hidden;
        }
        
        .events-panel.open {
            right: 0;
        }
        
        .panel-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            font-size: 1.3em;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .panel-close {
            background: rgba(255,255,255,0.3);
            border: none;
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1.2em;
            transition: background 0.2s;
        }
        
        .panel-close:hover {
            background: rgba(255,255,255,0.5);
        }
        
        .events-scroll {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }
        
        .event-card {
            border-left: 4px solid #667eea;
            padding: 15px;
            margin-bottom: 15px;
            background: #f9f9f9;
            border-radius: 4px;
            transition: all 0.2s;
        }
        
        .event-card:hover {
            background: #f0f0f0;
            transform: translateX(4px);
        }
        
        .event-time {
            font-size: 0.85em;
            color: #667eea;
            font-weight: 600;
            margin-bottom: 4px;
        }
        
        .event-title {
            font-weight: 600;
            font-size: 1em;
            color: #333;
            margin-bottom: 4px;
        }
        
        .event-venue {
            font-size: 0.9em;
            color: #666;
            margin-bottom: 4px;
        }
        
        .event-desc {
            font-size: 0.85em;
            color: #999;
            line-height: 1.4;
        }
        
        .no-events {
            padding: 40px 20px;
            text-align: center;
            color: #999;
        }
        
        .mobile-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 999;
        }
        
        .mobile-overlay.open {
            display: block;
        }
        
        @media (max-width: 768px) {
            .calendar-grid {
                grid-template-columns: 1fr;
            }
            
            .events-panel {
                width: 100%;
                right: -100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📅 Ann Arbor Events Calendar</h1>
            <p>Click any date to view events</p>
        </div>
        
        <div class="calendar-grid" id="calendarGrid">
""")
    
    # Generate calendar months
    current_month = min_month
    while current_month <= max_month:
        year = current_month.year
        month = current_month.month
        grid, first_day = _get_month_dates(year, month)
        
        month_name = first_day.strftime("%B %Y")
        
        html_parts.append(f'''
        <div class="month-container">
            <div class="month-header">{month_name}</div>
            <div class="weekday-header">
                <div class="weekday">Mon</div>
                <div class="weekday">Tue</div>
                <div class="weekday">Wed</div>
                <div class="weekday">Thu</div>
                <div class="weekday">Fri</div>
                <div class="weekday">Sat</div>
                <div class="weekday">Sun</div>
            </div>
            <div class="day-grid">
''')
        
        for day in grid:
            if day == 0:
                html_parts.append('<div class="day-cell empty"></div>')
            else:
                date_str = f"{year:04d}-{month:02d}-{day:02d}"
                day_events = events_by_date.get(date_str, [])
                event_count = len(day_events)
                
                if event_count > 0:
                    html_parts.append(f'''
                <div class="day-cell has-events" onclick="showEvents('{date_str}')">
                    <div class="day-number">{day}</div>
                    <div class="event-count">{event_count} event{"" if event_count == 1 else "s"}</div>
                </div>
''')
                else:
                    html_parts.append(f'''
                <div class="day-cell" onclick="showEvents('{date_str}')">
                    <div class="day-number">{day}</div>
                </div>
''')
        
        html_parts.append('''
            </div>
        </div>
''')
        
        # Move to next month
        if month == 12:
            current_month = datetime(year + 1, 1, 1)
        else:
            current_month = datetime(year, month + 1, 1)
    
    # Events panel
    html_parts.append('''
    </div>
    </div>
    
    <div class="mobile-overlay" id="mobileOverlay" onclick="closeEvents()"></div>
    
    <div class="events-panel" id="eventsPanel">
        <div class="panel-header">
            <span id="panelDateTitle">Events</span>
            <button class="panel-close" onclick="closeEvents()">✕</button>
        </div>
        <div class="events-scroll" id="eventsScroll">
        </div>
    </div>
    
    <script>
        const eventsByDate = ''')
    
    # Embed events data as JSON
    import json
    events_json = {}
    for date, day_events in events_by_date.items():
        events_json[date] = [
            {
                'time': _format_time_range(e),
                'title': e.title,
                'venue': e.venue or '',
                'description': (e.description or '')[:150],
                'source': e.source_name or '',
                'url': e.source_url or ''
            }
            for e in day_events
        ]
    
    html_parts.append(json.dumps(events_json))
    
    html_parts.append(''';
        
        function showEvents(dateStr) {
            const events = eventsByDate[dateStr] || [];
            const panelDateTitle = document.getElementById('panelDateTitle');
            const eventsScroll = document.getElementById('eventsScroll');
            const eventsPanel = document.getElementById('eventsPanel');
            const mobileOverlay = document.getElementById('mobileOverlay');
            
            // Format date for display
            const date = new Date(dateStr + 'T00:00:00');
            const dayName = date.toLocaleDateString('en-US', {weekday: 'long'});
            const monthDay = date.toLocaleDateString('en-US', {month: 'long', day: 'numeric'});
            panelDateTitle.textContent = dayName + ', ' + monthDay;
            
            // Build event cards
            if (events.length === 0) {
                eventsScroll.innerHTML = '<div class="no-events">No events scheduled</div>';
            } else {
                eventsScroll.innerHTML = events.map(e => `
                    <div class="event-card">
                        <div class="event-time">${e.time}</div>
                        <div class="event-title">${e.title}</div>
                        ${e.venue ? `<div class="event-venue">${e.venue}</div>` : ''}
                        ${e.description ? `<div class="event-desc">${e.description}...</div>` : ''}
                        ${e.url ? `<div style="margin-top: 8px;"><a href="${e.url}" target="_blank" style="color: #667eea; text-decoration: none; font-weight: 500;">View details →</a></div>` : ''}
                    </div>
                `).join('');
            }
            
            // Open panel
            eventsPanel.classList.add('open');
            mobileOverlay.classList.add('open');
        }
        
        function closeEvents() {
            document.getElementById('eventsPanel').classList.remove('open');
            document.getElementById('mobileOverlay').classList.remove('open');
        }
    </script>
</body>
</html>
''')
    
    return "\n".join(html_parts)
