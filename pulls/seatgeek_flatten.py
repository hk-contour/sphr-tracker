#!/usr/bin/env python3
"""Flatten paged SeatGeek JSON → data/seatgeek_schedule.csv"""
import json, csv, os, glob
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PAGES_DIR = f'{ROOT}/data/seatgeek_pages'
OUT_CSV = f'{ROOT}/data/seatgeek_schedule.csv'

poll_ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

all_events = []
for p in sorted(glob.glob(f'{PAGES_DIR}/page_*.json')):
    with open(p) as f:
        all_events.extend(json.load(f)['events'])

rows = []
for e in all_events:
    integ = e.get('integrated') or {}
    rows.append({
        'poll_ts_utc': poll_ts,
        'sg_event_id': e['id'],
        'datetime_local': e.get('datetime_local'),
        'datetime_utc': e.get('datetime_utc'),
        'weekday': datetime.fromisoformat(e['datetime_local']).strftime('%a') if e.get('datetime_local') else '',
        'show_time': (e.get('datetime_local') or '')[11:16],
        'tm_event_id': integ.get('provider_id') if integ.get('provider_name') == 'TICKETMASTER' else '',
        'sg_score': e.get('score'),
        'sg_popularity': e.get('popularity'),
        'url': e.get('url'),
    })

rows.sort(key=lambda r: r['datetime_local'] or '')

with open(OUT_CSV, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)

print(f'Wrote {len(rows)} rows → {OUT_CSV}')
print(f'Date range: {rows[0]["datetime_local"][:10]} → {rows[-1]["datetime_local"][:10]}')
print(f'TM event IDs available: {sum(1 for r in rows if r["tm_event_id"])}/{len(rows)}')
