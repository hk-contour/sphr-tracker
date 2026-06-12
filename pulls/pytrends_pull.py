#!/usr/bin/env python3
"""
Pull weekly Google Trends RSV for the Wizard of Oz / Sphere keyword basket.

Google's anti-bot now rejects vanilla HTTP calls (HTTP 429 on widgetdata endpoint
even with primed NID cookie). We use Playwright headless Chromium to make the
fetches from inside a real browser context — bypasses fingerprint detection.

Output: data/pytrends_history.csv
Schema: poll_ts_utc, week_start, keyword, rsv (0-100), has_data
"""
import os, csv, json, asyncio, random
from datetime import datetime, timezone
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT_CSV = f'{ROOT}/data/pytrends_history.csv'

# Google Trends API caps at 5 keywords per request, so we pull two batches.
# Batch A = the core direct-intent queries; Batch B = related/broader.
# 'Sphere Las Vegas' appears in both as the anchor, so both batches are scaled
# by a common reference (Google's RSV is relative within a single request).
BATCH_A = [
    'Sphere Las Vegas',           # anchor — highest-volume Sphere query
    'Sphere Vegas',
    'Sphere Las Vegas tickets',
    'Wizard of Oz Sphere',
    'Sphere tickets',
]
BATCH_B = [
    'Sphere Las Vegas',           # same anchor
    'MSG Sphere',
    'Sphere show',
    'Wizard of Oz tickets',
    'Wizard of Oz movie',
]
ANCHOR = 'Sphere Las Vegas'
TIMEFRAME = 'today 12-m'
GEO = 'US'
HL = 'en-US'
TZ = '240'

async def fetch_one_batch(page, keywords, max_attempts=3):
    """Pull a 5-keyword RSV time series. Retries on 429 with backoff."""
    explore_req = {
        'comparisonItem': [{'keyword': kw, 'geo': GEO, 'time': TIMEFRAME} for kw in keywords],
        'category': 0,
        'property': '',
    }

    last_err = None
    for attempt in range(max_attempts):
        try:
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

            # Small jitter to avoid back-to-back hits Google flags
            await asyncio.sleep(2 + random.random() * 2)

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
            return series
        except Exception as e:
            last_err = e
            backoff = 10 * (attempt + 1) + random.random() * 5
            print(f'  batch attempt {attempt+1} failed ({e!s}), sleeping {backoff:.0f}s...')
            await asyncio.sleep(backoff)
    raise last_err

async def fetch_trends():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = await ctx.new_page()
        await page.goto('https://trends.google.com/trends/?geo=US', wait_until='domcontentloaded')

        print('Fetching batch A (5 keywords)...')
        series_a = await fetch_one_batch(page, BATCH_A)

        # Sleep between batches so Google doesn't 429 the second one
        await asyncio.sleep(8 + random.random() * 4)

        print('Fetching batch B (5 keywords)...')
        series_b = await fetch_one_batch(page, BATCH_B)

        await browser.close()
        return series_a, series_b

def extract_rows(series, keywords, batch_label, poll_ts):
    """Flatten one batch's timeline into per-(week, keyword) rows."""
    rows = []
    for point in series['default']['timelineData']:
        week_start = datetime.fromtimestamp(int(point['time']), tz=timezone.utc).strftime('%Y-%m-%d')
        for i, kw in enumerate(keywords):
            rows.append({
                'poll_ts_utc': poll_ts,
                'week_start': week_start,
                'keyword': kw,
                'rsv': point['value'][i],
                'batch': batch_label,
                'has_data': bool(point['hasData'][i]) if 'hasData' in point else True,
            })
    return rows

def main():
    series_a, series_b = asyncio.run(fetch_trends())

    poll_ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    rows_a = extract_rows(series_a, BATCH_A, 'A', poll_ts)
    rows_b = extract_rows(series_b, BATCH_B, 'B', poll_ts)

    # Normalize batch B to batch A's anchor so all 10 keywords share a scale.
    # Scale factor = max(anchor in A) / max(anchor in B)
    max_a = max(r['rsv'] for r in rows_a if r['keyword'] == ANCHOR) or 1
    max_b = max(r['rsv'] for r in rows_b if r['keyword'] == ANCHOR) or 1
    scale = max_a / max_b
    print(f'Anchor "{ANCHOR}": max in batch A = {max_a}, max in batch B = {max_b}, scale = {scale:.3f}')

    for r in rows_b:
        r['rsv'] = round(r['rsv'] * scale, 1)

    # Drop duplicate anchor rows from batch B (keep batch A's authoritative values)
    rows_b = [r for r in rows_b if r['keyword'] != ANCHOR]

    all_rows = rows_a + rows_b
    with open(OUT_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=all_rows[0].keys())
        w.writeheader()
        w.writerows(all_rows)

    print(f'Wrote {len(all_rows)} rows → {OUT_CSV}')
    weeks = sorted({r['week_start'] for r in all_rows})
    keywords_all = sorted({r['keyword'] for r in all_rows})
    print(f'Weeks: {weeks[0]} → {weeks[-1]} ({len(weeks)})')
    print(f'Keywords ({len(keywords_all)}): {keywords_all}')

    print(f'\nLast 4w avg RSV vs prior 4w avg (post-normalization):')
    for kw in keywords_all:
        kw_rows = sorted([r for r in all_rows if r['keyword'] == kw], key=lambda r: r['week_start'])
        last4 = [r['rsv'] for r in kw_rows[-4:]]
        prev4 = [r['rsv'] for r in kw_rows[-8:-4]] if len(kw_rows) >= 8 else [0]
        a = sum(last4) / len(last4)
        b = sum(prev4) / len(prev4)
        delta = (a - b) / b * 100 if b else 0
        print(f'  {kw:<30} {b:>6.1f} → {a:>6.1f}   ({delta:+.0f}%)')

if __name__ == '__main__':
    main()
