#!/usr/bin/env python3
"""
Scrape TM "Quick Picks" (best-available seats) per Wizard of Oz showtime.

Per render (~25 credits with stealth proxy):
- 40 quickpick offers per event with section + row + price + ticket type
- Min/max face price range from the price slider
- Page title (sanity)

Output: data/tm_seatmap_history.csv (append-only — one row per (event, poll, quickpick))
"""
import os, csv, re, sys
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import http.client
http.client._MAXHEADERS = 1000  # ScrapingBee can return many headers
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT_CSV = f'{ROOT}/data/tm_seatmap_history.csv'

# Load creds
env = {}
with open(f'{ROOT}/.env') as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            env[k] = v
SB_KEY = env['SCRAPINGBEE_API_KEY']

def render(url, wait_ms=10000):
    r = requests.get('https://app.scrapingbee.com/api/v1/', params={
        'api_key': SB_KEY,
        'url': url,
        'render_js': 'true',
        'wait': str(wait_ms),  # longer wait ensures quickpicks JS finishes
        'block_resources': 'false',
        'country_code': 'us',
        'stealth_proxy': 'true',
    }, timeout=180)
    return r

def parse(html, event_meta):
    soup = BeautifulSoup(html, 'html.parser')

    # Min/max price from the price slider
    min_input = soup.find('input', attrs={'aria-label': re.compile(r'Minimum price')})
    max_input = soup.find('input', attrs={'aria-label': re.compile(r'Maximum price')})
    price_min = min_input.get('min') if min_input else ''
    price_max = max_input.get('max') if max_input else ''

    # Sold-out indicator
    page_text = soup.get_text(' ', strip=True)
    is_sold_out = 'Tickets are sold out now' in page_text or 'no inventory' in page_text.lower()

    # Quickpicks
    qp_items = soup.find_all(attrs={'data-bdd': re.compile(r'^quick-picks-list-item-primary-')})

    rows = []
    poll_ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for it in qp_items:
        price_attr = (it.get('data-price') or '').replace('$', '').replace(',', '')
        try:
            price_num = float(price_attr) if price_attr else None
        except ValueError:
            price_num = None

        text = it.get_text(' | ', strip=True)
        # Parse "Sec 406 • Row 19 | Standard Admission | $104.00"
        sec_m = re.search(r'Sec\s+([\w\s\-]+?)(?:\s*[•·]|\|)', text)
        row_m = re.search(r'Row\s+([\w\-]+)', text)
        section = sec_m.group(1).strip() if sec_m else ''
        row = row_m.group(1).strip() if row_m else ''
        # ticket type — text between section/row and the price
        type_m = re.search(r'(?:Row\s+[\w\-]+\s*\|\s*)([^|]+?)(?:\s*\|\s*\$)', text)
        ticket_type = type_m.group(1).strip() if type_m else ''

        rows.append({
            'poll_ts_utc': poll_ts,
            'tm_event_url': event_meta['url'],
            'event_date': event_meta['date'],
            'event_time': event_meta['time'],
            'section': section,
            'row': row,
            'ticket_type': ticket_type,
            'price': price_num,
            'is_sold_out': is_sold_out,
            'face_price_min': price_min,
            'face_price_max': price_max,
        })

    return rows, {'is_sold_out': is_sold_out, 'price_min': price_min, 'price_max': price_max}

def append_rows(rows):
    if not rows:
        return
    header_needed = not os.path.exists(OUT_CSV) or os.path.getsize(OUT_CSV) == 0
    with open(OUT_CSV, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        if header_needed:
            w.writeheader()
        w.writerows(rows)

def scrape_event(e, idx, total):
    meta = {'url': e['url'], 'date': e['local_date'], 'time': e['local_time']}
    print(f'[{idx+1}/{total}] {meta["date"]} {meta["time"]} ...', end=' ', flush=True)
    try:
        r = render(meta['url'])
    except Exception as ex:
        print(f'⚠ render error: {ex}')
        return 0
    if r.status_code != 200:
        print(f'⚠ HTTP {r.status_code}')
        return 0
    rows, summary = parse(r.text, meta)
    append_rows(rows)
    bestprice = min((row['price'] for row in rows if row['price']), default=None)
    print(f'{len(rows)} qp · face ${summary["price_min"]}–${summary["price_max"]}+ · best ${bestprice}')
    return len(rows)

def main():
    """
    Default: scrape ALL upcoming shows in the next 30 days.
    CLI overrides:
      --days N      : forward window in days (default 30)
      --max N       : cap number of events scraped (for credit budgeting)
      --index N     : scrape a single event by index (for testing)
    """
    days = 30
    cap = None
    single_idx = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--days':
            days = int(args[i+1]); i += 2
        elif a == '--max':
            cap = int(args[i+1]); i += 2
        elif a == '--index':
            single_idx = int(args[i+1]); i += 2
        else:
            # legacy: bare integer = index
            try:
                single_idx = int(a); i += 1
            except ValueError:
                print(f'Unknown arg: {a}'); raise SystemExit(2)

    with open(f'{ROOT}/data/tm_discovery_history.csv') as f:
        events = list(csv.DictReader(f))
    today_d = datetime.now().date()
    today = today_d.isoformat()
    horizon = (today_d + timedelta(days=days)).isoformat()
    upcoming = sorted(
        [e for e in events if today <= e['local_date'] <= horizon],
        key=lambda r: r['datetime_local'],
    )

    if single_idx is not None:
        scrape_event(upcoming[single_idx], single_idx, len(upcoming))
        return

    if cap:
        upcoming = upcoming[:cap]

    print(f'Scraping {len(upcoming)} events in window {today} → {horizon}\n')
    total_qp = 0
    for i, e in enumerate(upcoming):
        total_qp += scrape_event(e, i, len(upcoming))
    print(f'\nDone. {total_qp} total quickpick rows appended → {OUT_CSV}')

if __name__ == '__main__':
    main()
