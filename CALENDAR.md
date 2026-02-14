# Interactive Event Calendar

The vibescraper now generates an **interactive HTML calendar** (`calendar.html`) alongside the traditional Markdown files.

## Features

✨ **Monthly Calendar View** — Events organized in an intuitive calendar grid layout

🖱️ **Click to View** — Click any date to see all events for that day in a scrollable panel

📱 **Responsive Design** — Works seamlessly on desktop and mobile devices

🎨 **Beautiful UI** — Modern gradient design with smooth animations

🔍 **Event Details** — Each event shows time, venue, and description

## How to Use

1. Generate the calendar:
   ```bash
   vibescraper publish
   ```

2. Open `output/calendar.html` in your web browser

3. Click any date with events to view details

4. Click the × button to close the event panel

## Files Generated

- **EVENTS.md** — Traditional Markdown list of all upcoming events
- **ARCHIVE.md** — Past events organized by month
- **calendar.html** — Interactive calendar view (NEW)

## Calendar Layout

- Each month is displayed as a separate card
- Days with events are highlighted and show the event count
- Click any day to view all events for that date
- Responsive grid adjusts to screen size

## Technical Details

The calendar is a single, self-contained HTML file with:
- Embedded CSS for styling
- Embedded JavaScript for interactivity
- Event data embedded as JSON
- No external dependencies required
