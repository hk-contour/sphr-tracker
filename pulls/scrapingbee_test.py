#!/usr/bin/env python3
"""
One-shot test: render a single TM event page via ScrapingBee, parse it for
price tiers and seat-level availability indicators.

Starts cheap (no premium proxy = 5 credits). If TM blocks ScrapingBee's
datacenter IPs, we'll switch to premium proxy (25 credits/req).
"""
import os, csv, json, re
from datetime import datetime
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
env = {}
with open(f'{ROOT}/.env') as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            env[k] = v
SB_KEY = env['SCRAPINGBEE_API_KEY']

# Pick first upcoming event from TM Discovery snapshot
with open(f'{ROOT}/data/tm_discovery_history.csv') as f:
    events = list(csv.DictReader(f))
today = datetime.now().strftime('%Y-%m-%d')
upcoming = sorted([e for e in events if e['local_date'] >= today], key=lambda r: r['datetime_local'])
event = upcoming[0]
print(f'Testing event: {event["name"]}')
print(f'  Date/time:    {event["local_date"]} {event["local_time"]}')
print(f'  TM disc ID:   {event["tm_disc_event_id"]}')
print(f'  URL:          {event["url"]}')

def render(url, mode='basic'):
    """mode: basic | premium | stealth"""
    params = {
        'api_key': SB_KEY,
        'url': url,
        'render_js': 'true',
        'wait': '5000',
        'block_resources': 'false',  # don't block — helps with anti-bot
        'country_code': 'us',
    }
    if mode == 'premium':
        params['premium_proxy'] = 'true'
    elif mode == 'stealth':
        params['stealth_proxy'] = 'true'
    print(f'\nCalling ScrapingBee (mode={mode})...')
    r = requests.get('https://app.scrapingbee.com/api/v1/', params=params, timeout=180)
    return r

# Try escalating modes
for mode in ['stealth']:  # skip basic/premium since they failed — go straight to stealth
    r = render(event['url'], mode=mode)
    print(f'  HTTP {r.status_code}, {len(r.text):,} bytes')
    print(f'  Credits remaining: {r.headers.get("Spb-Credits-Remaining", "?")}')
    if r.status_code == 200 and len(r.text) > 10_000:
        break

html = r.text
out_html = f'{ROOT}/data/scrapingbee_test.html'
with open(out_html, 'w') as f:
    f.write(html)
print(f'\nSaved → {out_html}')

# ---- Probe the response for useful content ----
print('\n' + '=' * 60)
print('PROBING RESPONSE')
print('=' * 60)

# Check for known block / challenge markers
markers = ['Identity Verified', 'verify you are human', 'access denied',
           'captcha-delivery', 'Imperva', '"response":"identify"', '"response":"block"']
hits = [m for m in markers if m.lower() in html.lower()]
if hits:
    print(f'⚠ Block markers found: {hits}')
else:
    print('✓ No block markers found')

# Title sanity
m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
if m:
    print(f'Title: {m.group(1).strip()[:100]}')

# Look for embedded state blobs
patterns = [
    (r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\});\s*</script>', 'INITIAL_STATE'),
    (r'window\.__REDUX_STATE__\s*=\s*(\{.+?\});\s*</script>', 'REDUX_STATE'),
    (r'window\.__APP_STATE__\s*=\s*(\{.+?\});\s*</script>', 'APP_STATE'),
    (r'window\.__PRELOADED_STATE__\s*=\s*(\{.+?\});\s*</script>', 'PRELOADED_STATE'),
    (r'window\.__NEXT_DATA__\s*=\s*(\{.+?\})\s*</script>', 'NEXT_DATA'),
    (r'<script[^>]*id="__NEXT_DATA__"[^>]*>(\{.+?\})</script>', 'NEXT_DATA_TAG'),
    (r'<script[^>]*type="application/json"[^>]*>(\{.+?"event".+?\})</script>', 'INLINE_JSON'),
]
found_state = False
for pat, name in patterns:
    m = re.search(pat, html, re.DOTALL)
    if m:
        found_state = True
        blob = m.group(1)
        out_json = f'{ROOT}/data/scrapingbee_state_{name}.json'
        with open(out_json, 'w') as f:
            f.write(blob)
        print(f'\n✓ Found {name} blob ({len(blob):,} chars) → {out_json}')
        try:
            data = json.loads(blob)
            print(f'  Top-level keys: {list(data.keys())[:15]}')
        except Exception as e:
            print(f'  ⚠ JSON parse failed: {e}')

if not found_state:
    print('\n⚠ No embedded state blob found in known patterns')

# Look for dollar amounts in the visible HTML
prices = re.findall(r'\$\s?(\d{2,4}(?:\.\d{2})?)', html)
unique_prices = sorted(set(prices), key=lambda x: float(x))
print(f'\nDollar amounts found in HTML: {len(prices)} total, {len(unique_prices)} unique')
if unique_prices:
    print(f'  Unique values: {unique_prices[:20]}')

# Look for availability language
avail_words = re.findall(r'\b(sold out|limited|few left|available|on sale|standing room)\b', html, re.IGNORECASE)
if avail_words:
    print(f'\nAvailability language matches: {len(avail_words)} (sample: {avail_words[:5]})')

# Look for section names / seat counts
section_hits = re.findall(r'"(section|row|seat)"\s*:\s*"([^"]+)"', html)
print(f'\nSection/row/seat JSON keys found: {len(section_hits)} matches (showing first 10)')
for k, v in section_hits[:10]:
    print(f'  {k}: {v}')
