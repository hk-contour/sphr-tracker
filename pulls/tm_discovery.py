#!/usr/bin/env python3
"""
Pull Ticketmaster Discovery API data for Wizard of Oz at Sphere events.

Discovery API uses its own event IDs (different from SeatGeek's TM provider_id),
so we search by keyword + venue rather than mapping IDs.

Limitations confirmed in testing:
  - priceRanges field is null on all WoZ events (TM doesn't surface face value via Discovery)
  - No seat-level availability
  - We DO get: status code (onsale/offsale/cancelled), sales window dates, show count

Output: data/tm_discovery_history.csv (append-only — one row per (tm_disc_event_id, poll_ts))
"""
import os, csv, time
from datetime import datetime, timezone
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT_CSV = f'{ROOT}/data/tm_discovery_history.csv'

# Load API key
env = {}
with open(f'{ROOT}/.env') as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            env[k] = v
API_KEY = env.get('TM_DISCOVERY_API_KEY')
if not API_KEY:
    raise SystemExit('TM_DISCOVERY_API_KEY missing from .env')

SEARCH_URL = 'https://app.ticketmaster.com/discovery/v2/events.json'
KEYWORD = 'wizard of oz sphere'
PAGE_SIZE = 200  # API max

poll_ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
all_events = []
page = 0

while True:
    print(f'Fetching page {page}...')
    r = requests.get(SEARCH_URL, params={
        'apikey': API_KEY,
        'keyword': KEYWORD,
        'size': PAGE_SIZE,
        'page': page,
    }, timeout=20)

    if r.status_code == 429:
        print('  rate limited, sleeping 60s')
        time.sleep(60)
        continue
    r.raise_for_status()
    d = r.json()

    events = d.get('_embedded', {}).get('events', [])
    if not events:
        break
    all_events.extend(events)
    total = d.get('page', {}).get('totalElements', 0)
    total_pages = d.get('page', {}).get('totalPages', 0)
    print(f'  got {len(events)} events (running {len(all_events)}/{total}, page {page+1}/{total_pages})')

    if page + 1 >= total_pages:
        break
    page += 1
    time.sleep(0.25)

print(f'\nTotal events fetched: {len(all_events)}')

# Flatten
rows = []
for e in all_events:
    dates = e.get('dates', {})
    start = dates.get('start', {})
    status = dates.get('status', {})
    sales_public = e.get('sales', {}).get('public', {})
    pr = e.get('priceRanges') or []

    rows.append({
        'poll_ts_utc': poll_ts,
        'tm_disc_event_id': e['id'],
        'name': e.get('name', ''),
        'local_date': start.get('localDate', ''),
        'local_time': start.get('localTime', ''),
        'datetime_local': f"{start.get('localDate','')}T{start.get('localTime','')}",
        'status_code': status.get('code', ''),
        'price_min': min((p.get('min', 0) for p in pr), default=''),
        'price_max': max((p.get('max', 0) for p in pr), default=''),
        'on_sale_start': sales_public.get('startDateTime', ''),
        'on_sale_end': sales_public.get('endDateTime', ''),
        'url': e.get('url', ''),
    })

rows.sort(key=lambda r: r['datetime_local'])

# Append to history CSV
header_needed = not os.path.exists(OUT_CSV)
with open(OUT_CSV, 'a', newline='') as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    if header_needed:
        w.writeheader()
    w.writerows(rows)

print(f'Wrote {len(rows)} rows → {OUT_CSV}')

# Summary
from collections import Counter
status_counts = Counter(r['status_code'] for r in rows)
print(f'\nStatus distribution:')
for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
    print(f'  {s:<15} {c}')

priced = [r for r in rows if r['price_min'] != '']
print(f'\nEvents with priceRanges populated: {len(priced)}/{len(rows)}')
print(f'(Confirmed: TM Discovery does not surface face price for these residency shows)')

dates_set = sorted({r['local_date'] for r in rows if r['local_date']})
print(f'\nDate coverage: {dates_set[0]} → {dates_set[-1]} ({len(dates_set)} distinct dates)')
