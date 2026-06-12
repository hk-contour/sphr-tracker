#!/usr/bin/env python3
"""
Scrape TM "Quick Picks" (best-available seats) per Wizard of Oz showtime.

Per render (~25 credits with stealth proxy):
- 40 quickpick offers per event with section + row + price + ticket type
- Min/max face price range from the price slider
- Page title (sanity)

Output: data/tm_seatmap_history.csv (append-only — one row per (event, poll, quickpick))
"""
import os, csv, re, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import http.client
http.client._MAXHEADERS = 1000  # ScrapingBee can return many headers
import requests

_csv_lock = threading.Lock()

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
    with _csv_lock:
        header_needed = not os.path.exists(OUT_CSV) or os.path.getsize(OUT_CSV) == 0
        with open(OUT_CSV, 'a', newline='') as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            if header_needed:
                w.writeheader()
            w.writerows(rows)

def append_zero_marker(meta, face_min='', face_max=''):
    """Mark a 0-quickpick event in the CSV so the chart can show it as a sellout."""
    poll_ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    row = {
        'poll_ts_utc': poll_ts,
        'tm_event_url': meta['url'],
        'event_date': meta['date'],
        'event_time': meta['time'],
        'section': '', 'row': '', 'ticket_type': '',
        'price': '', 'is_sold_out': True,
        'face_price_min': face_min, 'face_price_max': face_max,
    }
    append_rows([row])

def scrape_event(e, idx, total):
    meta = {'url': e['url'], 'date': e['local_date'], 'time': e['local_time']}
    try:
        r = render(meta['url'])
    except Exception as ex:
        print(f'[{idx+1}/{total}] {meta["date"]} {meta["time"]} ⚠ render error: {ex}')
        return 0
    if r.status_code != 200:
        print(f'[{idx+1}/{total}] {meta["date"]} {meta["time"]} ⚠ HTTP {r.status_code}')
        return 0
    rows, summary = parse(r.text, meta)
    # Retry once with longer wait if we got 0 quickpicks — disambiguates render-miss vs real sellout
    if not rows:
        try:
            r2 = render(meta['url'], wait_ms=15000)
            if r2.status_code == 200:
                rows, summary = parse(r2.text, meta)
        except Exception:
            pass

    if rows:
        append_rows(rows)
        bestprice = min((row['price'] for row in rows if row['price']), default=None)
        print(f'[{idx+1}/{total}] {meta["date"]} {meta["time"]} → {len(rows)} qp · face ${summary["price_min"]}–${summary["price_max"]}+ · best ${bestprice}')
    else:
        # Persist the zero-quickpick fact so we can chart it as a sellout
        append_zero_marker(meta, summary.get('price_min', ''), summary.get('price_max', ''))
        print(f'[{idx+1}/{total}] {meta["date"]} {meta["time"]} → 0 qp (sellout? face ${summary["price_min"]}–${summary["price_max"]}+)')
    return len(rows)

def main():
    """
    Default: scrape ALL upcoming shows in the next 14 days.
    CLI overrides:
      --days N              : forward window in days (default 14)
      --max N               : cap number of events scraped (for credit budgeting)
      --index N             : scrape a single event by index (for testing)
      --skip-polled-today   : skip events that already have a poll dated today
    """
    days = 14
    cap = None
    single_idx = None
    skip_polled_today = False
    workers = 8  # ScrapingBee Freelance allows max_concurrency=10; leave headroom
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
        elif a == '--workers':
            workers = int(args[i+1]); i += 2
        elif a == '--skip-polled-today':
            skip_polled_today = True; i += 1
        else:
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

    if skip_polled_today and os.path.exists(OUT_CSV):
        today_iso = today_d.isoformat()
        already = set()
        with open(OUT_CSV) as f:
            for row in csv.DictReader(f):
                if row['poll_ts_utc'].startswith(today_iso):
                    already.add((row['event_date'], row['event_time']))
        before = len(upcoming)
        upcoming = [e for e in upcoming if (e['local_date'], e['local_time']) not in already]
        print(f'Skipping {before - len(upcoming)} events already polled today\n')

    if cap:
        upcoming = upcoming[:cap]

    print(f'Scraping {len(upcoming)} events in window {today} → {horizon}  (workers={workers})\n')
    total_qp = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scrape_event, e, i, len(upcoming)): i for i, e in enumerate(upcoming)}
        for f in as_completed(futures):
            total_qp += f.result() or 0
    print(f'\nDone. {total_qp} total quickpick rows appended → {OUT_CSV}')

if __name__ == '__main__':
    main()
