# WebScraper Pro

A Python web scraping application with a sleek dashboard UI.

## Features
- **Keyword Search** — searches Google and automatically scrapes all results
- **URL Mode** — paste a list of URLs to scrape directly
- **Extracts**: emails, phone numbers, addresses, social links, contact/about pages, meta description
- **Dashboard** — filter, view and copy data instantly
- **Export** — download results as CSV or Excel

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the app**
   ```bash
   python app.py
   ```

3. **Open your browser**
   ```
   http://localhost:5000
   ```

## Usage

### Keyword Search
1. Click **Keyword Search** tab
2. Enter a search term (e.g. `french polishing London`)
3. Choose how many results (5–30)
4. Click **Search & Scrape**

### URL Mode
1. Click **Paste URLs** tab
2. Paste URLs, one per line
3. Click **Scrape URLs**

### Exporting
- Click **⬇ CSV** or **⬇ Excel** in the sidebar
- File downloads automatically

## Notes
- Google search rate-limits aggressive scraping — use reasonable result counts
- Some sites block scrapers via robots.txt or Cloudflare; they'll show as "down"
- Click any email or phone tag on a card to copy it to clipboard
