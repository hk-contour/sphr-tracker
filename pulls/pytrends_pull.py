#!/usr/bin/env python3
"""
Pull weekly Google Trends RSV for the Wizard of Oz / Sphere keyword basket.

Google's anti-bot now rejects vanilla HTTP calls (HTTP 429 on widgetdata endpoint
even with primed NID cookie). We use Playwright headless Chromium to make the
fetches from inside a real browser context — bypasses fingerprint detection.

Output: data/pytrends_history.csv
Schema: poll_ts_utc, week_start, keyword, rsv (0-100), has_data
"""
import os, csv, json, asyncio
from datetime import datetime, timezone
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT_CSV = f'{ROOT}/data/pytrends_history.csv'

KEYWORDS = [
    'Wizard of Oz Sphere',
    'Sphere Las Vegas tickets',
    'Sphere Las Vegas',
    'Sphere Vegas',
]
TIMEFRAME = 'today 12-m'
GEO = 'US'
HL = 'en-US'
TZ = '240'

async def fetch_trends():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = await ctx.new_page()
        await page.goto('https://trends.google.com/trends/?geo=US', wait_until='domcontentloaded')

        explore_req = {
            'comparisonItem': [{'keyword': kw, 'geo': GEO, 'time': TIMEFRAME} for kw in KEYWORDS],
            'category': 0,
            'property': '',
        }

        explore_data = await page.evaluate('''
            async (req) => {
                const url = '/trends/api/explore?hl=%s&tz=%s&req=' + encodeURIComponent(JSON.stringify(req));
                const r = await fetch(url);
                if (r.status !== 200) throw new Error('explore HTTP ' + r.status);
                const text = await r.text();
                const json_str = text.startsWith(")]}'") ? text.slice(4).trim() : text;
                return JSON.parse(json_str);
            }
        ''' % (HL, TZ), explore_req)

        ts_widget = next(w for w in explore_data['widgets'] if w['id'] == 'TIMESERIES')

        series = await page.evaluate('''
            async (args) => {
                const url = '/trends/api/widgetdata/multiline?hl=%s&tz=%s&req=' + encodeURIComponent(JSON.stringify(args.req)) + '&token=' + args.token;
                const r = await fetch(url);
                if (r.status !== 200) throw new Error('widgetdata HTTP ' + r.status);
                const text = await r.text();
                const json_str = text.startsWith(")]}'") ? text.slice(4).trim() : text;
                if (json_str.startsWith(',')) return JSON.parse(json_str.slice(1));
                return JSON.parse(json_str);
            }
        ''' % (HL, TZ), {'req': ts_widget['request'], 'token': ts_widget['token']})

        await browser.close()
        return series

def main():
    series = asyncio.run(fetch_trends())

    poll_ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    rows = []
    for point in series['default']['timelineData']:
        week_start = datetime.fromtimestamp(int(point['time']), tz=timezone.utc).strftime('%Y-%m-%d')
        for i, kw in enumerate(KEYWORDS):
            rows.append({
                'poll_ts_utc': poll_ts,
                'week_start': week_start,
                'keyword': kw,
                'rsv': point['value'][i],
                'has_data': bool(point['hasData'][i]) if 'hasData' in point else True,
            })

    with open(OUT_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    print(f'Wrote {len(rows)} rows → {OUT_CSV}')
    weeks = sorted({r['week_start'] for r in rows})
    print(f'Weeks covered: {weeks[0]} → {weeks[-1]} ({len(weeks)} weeks)')

    print(f'\nLast 4w avg RSV vs prior 4w avg:')
    for kw in KEYWORDS:
        kw_rows = sorted([r for r in rows if r['keyword'] == kw], key=lambda r: r['week_start'])
        last4 = [r['rsv'] for r in kw_rows[-4:]]
        prev4 = [r['rsv'] for r in kw_rows[-8:-4]] if len(kw_rows) >= 8 else [0]
        a = sum(last4) / len(last4)
        b = sum(prev4) / len(prev4)
        delta = (a - b) / b * 100 if b else 0
        print(f'  {kw:<35} {b:>5.1f} → {a:>5.1f}   ({delta:+.0f}%)')

if __name__ == '__main__':
    main()
