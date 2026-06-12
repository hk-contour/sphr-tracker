#!/usr/bin/env python3
"""
Generate dashboard.html from whatever CSVs exist in data/.

Reads:
  data/seatgeek_schedule.csv     (required)
  data/pytrends_history.csv      (optional)
  data/tm_discovery_history.csv  (optional)
  data/tm_seatmap_history.csv    (optional, headline panel)

Writes:
  dashboard.html — single-file static report with Chart.js via CDN.
"""
import os, csv, json
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = f'{ROOT}/data'
OUT = f'{ROOT}/index.html'  # named index.html so GitHub Pages serves it as the root page

def read_csv(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return list(csv.DictReader(f))

schedule = read_csv(f'{DATA}/seatgeek_schedule.csv')
trends = read_csv(f'{DATA}/pytrends_history.csv')
tm_disc = read_csv(f'{DATA}/tm_discovery_history.csv')
tm_seat = read_csv(f'{DATA}/tm_seatmap_history.csv')

# ---------- Schedule panel ----------
sched_data = {}
if schedule:
    months = Counter(r['datetime_local'][:7] for r in schedule)
    weekdays = Counter(r['weekday'] for r in schedule)
    times = Counter(r['show_time'] for r in schedule)
    sched_data = {
        'total': len(schedule),
        'first': schedule[0]['datetime_local'][:10],
        'last': schedule[-1]['datetime_local'][:10],
        'tm_ids': sum(1 for r in schedule if r['tm_event_id']),
        'months': [{'label': m, 'count': months[m]} for m in sorted(months)],
        'weekdays': [{'label': d, 'count': weekdays.get(d, 0)}
                     for d in ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']],
        'times': [{'label': t, 'count': times[t]} for t in sorted(times)],
        'poll_ts': schedule[0].get('poll_ts_utc', ''),
    }

# ---------- Trends panel ----------
trends_data = {}
if trends:
    by_kw = defaultdict(list)
    for r in trends:
        by_kw[r['keyword']].append((r['week_start'], float(r['rsv'])))
    series = {}
    for kw, pts in by_kw.items():
        pts.sort()
        series[kw] = {
            'weeks': [p[0] for p in pts],
            'rsv': [round(p[1], 1) for p in pts],
        }
    # Compute the headline 4w vs prior 4w delta for each keyword
    summary = []
    for kw, pts in by_kw.items():
        pts.sort()
        vals = [p[1] for p in pts]
        if len(vals) >= 8:
            last4, prev4 = sum(vals[-4:])/4, sum(vals[-8:-4])/4
            delta = (last4 - prev4) / prev4 * 100 if prev4 else 0
            summary.append({
                'kw': kw,
                'last4': round(last4, 1),
                'prev4': round(prev4, 1),
                'delta': round(delta, 1),
            })
    # Sort by current interest level (last4 avg, descending)
    summary.sort(key=lambda s: -s['last4'])
    trends_data = {
        'series': series,
        'summary': summary,
        'poll_ts': trends[0].get('poll_ts_utc', ''),
    }

# ---------- Headline string ----------
headline_bits = []
if sched_data:
    headline_bits.append(f'{sched_data["total"]} upcoming showtimes ({sched_data["first"]} → {sched_data["last"]})')
if trends_data and trends_data['summary']:
    broad = next((s for s in trends_data['summary'] if s['kw'] == 'Sphere Las Vegas'), None)
    if broad:
        sign = '+' if broad['delta'] >= 0 else ''
        headline_bits.append(f'"Sphere Las Vegas" search interest {sign}{broad["delta"]:.0f}% MoM')

headline = ' · '.join(headline_bits) if headline_bits else 'No data yet'

# ---------- TM Seatmap panel (computed up-front so it can render first) ----------
tm_seat_chart = None
panel_seatmap = ''
if tm_seat:
    from datetime import timedelta as _td
    today_d = datetime.now().date()
    window_start = today_d.isoformat()
    window_end = (today_d + _td(days=14)).isoformat()

    def fmt_label(date_str, time_str):
        """Pretty x-axis label: 'Jun 12 Fri 2pm' instead of '2026-06-12 14:00'."""
        d = datetime.strptime(date_str, '%Y-%m-%d')
        wd = d.strftime('%a')
        ds = d.strftime('%b %d')
        hh = int(time_str[:2])
        ampm = 'am' if hh < 12 else 'pm'
        hh12 = hh - 12 if hh > 12 else (12 if hh == 0 else hh)
        return f'{ds} {wd} {hh12}{ampm}'

    by_event = defaultdict(list)
    for r in tm_seat:
        if window_start <= r['event_date'] <= window_end:
            by_event[(r['event_date'], r['event_time'])].append(r)

    rows_per_event = []
    section_offers = defaultdict(int)
    all_quickpick_prices = []
    for key, rows in by_event.items():
        latest_ts = max(r['poll_ts_utc'] for r in rows)
        latest = [r for r in rows if r['poll_ts_utc'] == latest_ts]
        priced_latest = [r for r in latest if r['price'] not in ('', None)]
        prices = [float(r['price']) for r in priced_latest]
        is_sellout = (len(priced_latest) == 0)
        for r in priced_latest:
            if r['section']:
                section_offers[r['section']] += 1
            all_quickpick_prices.append(float(r['price']))
        d = datetime.strptime(key[0], '%Y-%m-%d')
        rows_per_event.append({
            'date': key[0],
            'time': key[1][:5],
            'datetime_label': fmt_label(key[0], key[1]),
            'weekday': d.strftime('%a'),
            'face_min': float(latest[0]['face_price_min']) if latest[0]['face_price_min'] not in ('', None) else None,
            'face_max': float(latest[0]['face_price_max']) if latest[0]['face_price_max'] not in ('', None) else None,
            'best_avail': min(prices) if prices else None,
            'qp_count': len(priced_latest),
            'is_sellout': is_sellout,
        })
    rows_per_event.sort(key=lambda r: (r['date'], r['time']))

    scraped_days = sorted({r['date'] for r in rows_per_event})
    sellouts = [r for r in rows_per_event if r['is_sellout']]
    total_days = 15
    avg_best = sum(r['best_avail'] for r in rows_per_event if r['best_avail']) / max(1, len([r for r in rows_per_event if r['best_avail']]))
    min_best = min((r['best_avail'] for r in rows_per_event if r['best_avail']), default=0)
    max_best = max((r['best_avail'] for r in rows_per_event if r['best_avail']), default=0)

    # Sellout markers placed at the average price so they show up alongside the other data
    sellout_y = avg_best if avg_best else 100

    tm_seat_chart = {
        'labels': [r['datetime_label'] for r in rows_per_event],
        'best_avail': [r['best_avail'] for r in rows_per_event],
        'face_max': [r['face_max'] for r in rows_per_event],
        'face_min': [r['face_min'] for r in rows_per_event],
        'sellout': [sellout_y if r['is_sellout'] else None for r in rows_per_event],
    }

    # Headline override: lead with the ticket-data summary
    headline = f'{len(rows_per_event)} shows scraped in next 14d · best-available ${min_best:.0f}–${max_best:.0f} (avg ${avg_best:.0f}) · {len(sellouts)} likely sellouts · ' + headline

    # Build sellout list for inline display
    sellouts_html = ''
    if sellouts:
        sellouts_html = '<h3>Likely sellouts (0 quickpicks after retry)</h3><table><tr><th>Date</th><th>Time</th><th>Face range</th></tr>'
        for s in sellouts:
            fmin = f'${s["face_min"]:.0f}' if s['face_min'] else '—'
            fmax = f'${s["face_max"]:.0f}+' if s['face_max'] else '—'
            sellouts_html += f'<tr><td>{s["date"]}</td><td>{s["time"]}</td><td>{fmin} – {fmax}</td></tr>'
        sellouts_html += '</table>'

    # === Per-time-of-day average best-available ===
    by_tod = defaultdict(list)
    for r in rows_per_event:
        if r['best_avail']:
            by_tod[r['time']].append(r['best_avail'])
    tod_data = sorted([(t, sum(v)/len(v), len(v)) for t, v in by_tod.items()])

    # === Per-weekday average best-available ===
    by_wd = defaultdict(list)
    for r in rows_per_event:
        if r['best_avail']:
            by_wd[r['weekday']].append(r['best_avail'])
    wd_order = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    wd_data = [(d, sum(by_wd[d])/len(by_wd[d]) if by_wd[d] else None, len(by_wd[d])) for d in wd_order]

    # === Price histogram across all quickpicks ===
    price_buckets = defaultdict(int)
    for p in all_quickpick_prices:
        bucket = int(p // 10) * 10  # $10 buckets
        price_buckets[bucket] += 1
    hist_labels = sorted(price_buckets.keys())
    hist_data = [price_buckets[b] for b in hist_labels]

    # === Section coverage ===
    section_table = ''
    if section_offers:
        section_table = '<table><tr><th>Section</th><th style="text-align:right;">Shows w/ best-available inventory here</th></tr>'
        for sec, count in sorted(section_offers.items(), key=lambda x: -x[1])[:15]:
            section_table += f'<tr><td>Sec {sec}</td><td style="text-align:right;">{count}</td></tr>'
        section_table += '</table>'

    tm_seat_chart['extra'] = {
        'tod_labels': [t[0] for t in tod_data],
        'tod_avgs':   [round(t[1], 2) for t in tod_data],
        'tod_counts': [t[2] for t in tod_data],
        'wd_labels':  wd_order,
        'wd_avgs':    [round(d[1], 2) if d[1] else None for d in wd_data],
        'wd_counts':  [d[2] for d in wd_data],
        'hist_labels': [f'${b}-{b+9}' for b in hist_labels],
        'hist_data':  hist_data,
    }

    panel_seatmap = f"""
<div class="panel" style="border-left: 4px solid #2563eb;">
  <div class="panel-title">Wizard of Oz · ticket prices — next 14 days</div>
  <div class="meta">Scraped from public Ticketmaster event pages via ScrapingBee. Each render returns up to 40 "best available" quickpicks per show (TM's lowest-priced offers). Window: {window_start} → {window_end}.</div>
  <div class="stat-row">
    <div class="stat">
      <div class="stat-label">Shows scraped in window</div>
      <div class="stat-value">{len(rows_per_event)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Likely sellouts <span title="A show that returned 0 quickpicks after a retry-with-longer-wait. Zero today means no shows currently appear sold-out at the lowest tier." style="color:#888;cursor:help;">ⓘ</span></div>
      <div class="stat-value" style="color:{'#dc2626' if sellouts else '#059669'};">{len(sellouts)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Best-available range</div>
      <div class="stat-value">${min_best:.0f}–${max_best:.0f}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Best-available avg</div>
      <div class="stat-value">${avg_best:.0f}</div>
    </div>
  </div>
  <div class="meta" style="background:#fff8e1;padding:10px 12px;border-radius:4px;margin:12px 0;">
    <strong>"Best-available" is the lowest-priced seat in the entire arena</strong> — so it stays at $104 as long as <em>any</em> upper-tier seat is for sale. Dynamic pricing happens on premium tiers (see <strong>Face max</strong>, $342–$349). When best-available jumps above $104, the cheapest tier has sold out for that show.
  </div>
  <h3>Price by show — 14-day window</h3>
  <div class="chart-container"><canvas id="seatPriceChart"></canvas></div>
  <div class="meta" style="margin-top:8px;">
    Each marker = one showtime. <span style="color:#2563eb;">●</span> best available ·
    <span style="color:#dc2626;">●</span> face max (premium tier ceiling) ·
    <span style="color:#888;">●</span> face min (dashed; lowest tier listed) ·
    <span style="color:#dc2626;">✕</span> likely sellout (0 quickpicks).
  </div>

  <div class="grid-2" style="margin-top:24px;">
    <div>
      <h3>Avg best-available by time of day</h3>
      <div class="meta">Compares matinee vs evening pricing across the window.</div>
      <div class="chart-container-small"><canvas id="todChart"></canvas></div>
    </div>
    <div>
      <h3>Avg best-available by weekday</h3>
      <div class="meta">Weekend vs weekday pricing.</div>
      <div class="chart-container-small"><canvas id="wdChart"></canvas></div>
    </div>
  </div>

  <h3>Quickpick price distribution (all offers across all shows)</h3>
  <div class="meta">Distribution of all {len(all_quickpick_prices)} quickpick prices in the 14-day window, $10 buckets. Reveals the underlying tier structure of "best available" offers.</div>
  <div class="chart-container-small"><canvas id="priceHistChart"></canvas></div>

  <h3>Section coverage (which sections appear most often in best-available)</h3>
  <div class="meta">Shows the sections feeding the "best available" pool — sections at the top of this list have the most unsold low-tier inventory across upcoming shows. (Premium sections rarely appear because they're not the cheapest tier.)</div>
  {section_table}

  {sellouts_html}
</div>"""

# ---------- Build HTML ----------
generated_ts = datetime.now().strftime('%Y-%m-%d %H:%M %Z')

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sphere demand monitor — Wizard of Oz</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 1200px; margin: 0 auto; padding: 24px; color: #1a1a1a;
         background: #fafafa; line-height: 1.5; }}
  h1 {{ margin: 0 0 4px; font-size: 24px; }}
  h2 {{ margin: 0 0 12px; font-size: 16px; color: #555; font-weight: 500; }}
  h3 {{ margin: 24px 0 8px; font-size: 14px; color: #333;
        border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; }}
  .meta {{ font-size: 12px; color: #888; margin-bottom: 16px; }}
  .headline {{ background: #fff; border-left: 4px solid #2563eb; padding: 12px 16px;
               margin-bottom: 24px; font-size: 14px; border-radius: 2px;
               box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  .panel {{ background: #fff; border-radius: 6px; padding: 16px; margin-bottom: 16px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  .panel-title {{ font-size: 13px; font-weight: 600; color: #333;
                  margin: 0 0 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .stat-row {{ display: flex; gap: 24px; margin-bottom: 12px; }}
  .stat {{ flex: 1; }}
  .stat-label {{ font-size: 11px; color: #888; text-transform: uppercase;
                 letter-spacing: 0.5px; }}
  .stat-value {{ font-size: 20px; font-weight: 600; color: #1a1a1a; margin-top: 2px; }}
  .chart-container {{ position: relative; height: 280px; }}
  .chart-container-small {{ position: relative; height: 200px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  .delta-pos {{ color: #059669; }}
  .delta-neg {{ color: #dc2626; }}
  .pending {{ color: #888; font-style: italic; padding: 24px; text-align: center;
              background: #f5f5f5; border-radius: 4px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 768px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>

<h1>Sphere demand monitor — Wizard of Oz</h1>
<h2>Daily refresh tracking SPHR's residency demand</h2>
<div class="meta">Generated {generated_ts}</div>

<div class="headline">📊 {headline}</div>

{panel_seatmap}

<div class="panel">
  <div class="panel-title">Schedule overview (SeatGeek)</div>
  <div class="meta">The supply side: every Wizard of Oz showtime Sphere has scheduled. This is the denominator we'd scrape ticket prices for. "TM Event IDs known" = how many shows we have Ticketmaster's internal ID for (needed to scrape).</div>
"""

if sched_data:
    html += f"""
  <div class="stat-row">
    <div class="stat">
      <div class="stat-label">Total upcoming showtimes</div>
      <div class="stat-value">{sched_data['total']}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Date range</div>
      <div class="stat-value" style="font-size:14px;">{sched_data['first']} → {sched_data['last']}</div>
    </div>
    <div class="stat">
      <div class="stat-label">TM event IDs known</div>
      <div class="stat-value">{sched_data['tm_ids']} / {sched_data['total']}</div>
    </div>
  </div>
  <div class="grid-2">
    <div>
      <h3>Showtimes per month</h3>
      <div class="chart-container-small"><canvas id="monthChart"></canvas></div>
    </div>
    <div>
      <h3>Showtimes per weekday</h3>
      <div class="chart-container-small"><canvas id="weekdayChart"></canvas></div>
    </div>
  </div>
  <h3>Time-of-day slots</h3>
  <div class="chart-container-small"><canvas id="timeChart"></canvas></div>
"""
else:
    html += '<div class="pending">No schedule data — run pulls/seatgeek.sh</div>'

html += '</div>\n\n<div class="panel"><div class="panel-title">Search interest (Google Trends)</div>'

if trends_data:
    html += '<div class="meta">Relative Search Volume (RSV, 0–100) from Google Trends — measures search interest, not absolute volume. All 9 keywords normalized to a common scale via the "Sphere Las Vegas" anchor.</div>'

    # === Current snapshot bar chart ===
    html += '<h3>Current 4-week avg interest, ranked</h3>'
    html += '<div class="chart-container-small"><canvas id="trendsBarChart"></canvas></div>'

    # === Deltas table ===
    html += '<h3>4-week MoM change per keyword</h3>'
    html += '<table><tr><th>Keyword</th><th style="text-align:right;">Prev 4w avg</th><th style="text-align:right;">Last 4w avg</th><th style="text-align:right;">Δ MoM</th></tr>'
    for s in trends_data['summary']:
        cls = 'delta-pos' if s['delta'] >= 0 else 'delta-neg'
        sign = '+' if s['delta'] >= 0 else ''
        html += f"""<tr>
          <td>{s['kw']}</td>
          <td style="text-align:right;">{s['prev4']:.1f}</td>
          <td style="text-align:right;">{s['last4']:.1f}</td>
          <td style="text-align:right;" class="{cls}">{sign}{s['delta']:.0f}%</td>
        </tr>"""
    html += '</table>'

    # === 12-month line chart (all keywords overlaid) ===
    html += '<h3>Weekly RSV — all keywords, 12-month trend</h3>'
    html += '<div class="chart-container"><canvas id="trendsChart"></canvas></div>'

    # === Sparkline grid — one mini-chart per keyword ===
    html += '<h3>Per-keyword sparklines (12-month, scaled to its own range)</h3>'
    html += '<div class="meta">Each tile scaled to its own min/max so the SHAPE of demand for each keyword is visible — not absolute level.</div>'
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:8px;">'
    for i, s in enumerate(trends_data['summary']):
        html += f"""
        <div style="background:#fafafa;border-radius:4px;padding:8px;">
          <div style="font-size:11px;color:#555;display:flex;justify-content:space-between;align-items:baseline;">
            <span style="font-weight:600;">{s['kw']}</span>
            <span class="{'delta-pos' if s['delta'] >= 0 else 'delta-neg'}">{'+' if s['delta'] >= 0 else ''}{s['delta']:.0f}%</span>
          </div>
          <div style="height:60px;position:relative;"><canvas id="sparkline-{i}"></canvas></div>
        </div>"""
    html += '</div>'
else:
    html += '<div class="pending">No trends data — run pulls/pytrends_pull.py</div>'

html += '</div>\n\n<div class="panel"><div class="panel-title">Ticketmaster Discovery (status + sales windows)</div>'
html += """<div class="meta">Slow-moving supply signal from Ticketmaster's free public API. Becomes useful when shows start flipping status (e.g. <code>onsale → offsale</code>).</div>
<div class="meta" style="background:#f0f9ff;padding:10px 12px;border-radius:4px;margin:12px 0;">
  <strong>Column legend:</strong>
  <ul style="margin:6px 0 0 18px;padding:0;font-size:12px;">
    <li><code>onsale</code> — tickets actively for sale via Ticketmaster right now</li>
    <li><code>offsale</code> — sales window closed (either sold out, or sales period ended). Becoming the key signal once we accumulate polling history.</li>
    <li><code>cancelled</code> — show pulled / cancelled</li>
    <li><code>other</code> — any non-standard status code (rescheduled, postponed, etc.)</li>
  </ul>
</div>"""
if tm_disc:
    # Latest poll snapshot
    latest_ts = max(r['poll_ts_utc'] for r in tm_disc)
    latest = [r for r in tm_disc if r['poll_ts_utc'] == latest_ts]
    today = datetime.now().strftime('%Y-%m-%d')
    upcoming = [r for r in latest if r['local_date'] >= today]
    past = [r for r in latest if r['local_date'] < today]
    status_counts = Counter(r['status_code'] for r in upcoming)
    priced = [r for r in upcoming if r['price_min'] not in ('', '0')]

    # Status by month over upcoming events
    by_month_status = defaultdict(lambda: Counter())
    for r in upcoming:
        m = r['local_date'][:7]
        by_month_status[m][r['status_code']] += 1
    months_sorted = sorted(by_month_status.keys())

    html += f"""
  <div class="stat-row">
    <div class="stat">
      <div class="stat-label">Upcoming events</div>
      <div class="stat-value">{len(upcoming)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Past events on record</div>
      <div class="stat-value">{len(past)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Currently <code>onsale</code></div>
      <div class="stat-value">{status_counts.get('onsale', 0)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">With face pricing</div>
      <div class="stat-value">{len(priced)} / {len(upcoming)}</div>
    </div>
  </div>
  <div class="meta">⚠ Discovery API does not expose face pricing or seat-level availability for this residency. We track status code transitions (onsale → offsale/cancelled) and the population of upcoming events as the daily signal.</div>
  <h3>Status by month (upcoming events only)</h3>
  <table><tr><th>Month</th><th style="text-align:right;">onsale</th><th style="text-align:right;">offsale</th><th style="text-align:right;">cancelled</th><th style="text-align:right;">other</th></tr>"""
    for m in months_sorted:
        c = by_month_status[m]
        other = sum(v for k, v in c.items() if k not in ('onsale', 'offsale', 'cancelled'))
        html += f'<tr><td>{m}</td><td style="text-align:right;">{c.get("onsale",0)}</td><td style="text-align:right;">{c.get("offsale",0)}</td><td style="text-align:right;">{c.get("cancelled",0)}</td><td style="text-align:right;">{other}</td></tr>'
    html += '</table>'
    html += f'<div class="meta" style="margin-top:12px;">Latest poll: {latest_ts} · {len(tm_disc)} total rows across all polls (signal becomes useful after 2+ weeks of accumulated polling)</div>'
else:
    html += """<div class="pending">
      Not yet wired. Needs free TM Discovery API key from <a href="https://developer.ticketmaster.com">developer.ticketmaster.com</a> →
      add to <code>.env</code> as <code>TM_DISCOVERY_API_KEY</code> → run <code>python3 pulls/tm_discovery.py</code>
    </div>"""
html += '</div>'


# ---------- JS for charts ----------
chart_data = {
    'schedule': sched_data,
    'trends': {
        **trends_data,
        'summary': trends_data.get('summary', []),
    } if trends_data else None,
    'tm_seat': tm_seat_chart,
}
html += f"""

<script>
const D = {json.dumps(chart_data)};

if (D.schedule && D.schedule.months) {{
  new Chart(document.getElementById('monthChart'), {{
    type: 'bar',
    data: {{
      labels: D.schedule.months.map(m => m.label),
      datasets: [{{ label: 'Shows', data: D.schedule.months.map(m => m.count),
                   backgroundColor: '#2563eb' }}],
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }},
                scales: {{ y: {{ beginAtZero: true }} }} }},
  }});
  new Chart(document.getElementById('weekdayChart'), {{
    type: 'bar',
    data: {{
      labels: D.schedule.weekdays.map(d => d.label),
      datasets: [{{ label: 'Shows', data: D.schedule.weekdays.map(d => d.count),
                   backgroundColor: '#059669' }}],
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }},
                scales: {{ y: {{ beginAtZero: true }} }} }},
  }});
  new Chart(document.getElementById('timeChart'), {{
    type: 'bar',
    data: {{
      labels: D.schedule.times.map(t => t.label),
      datasets: [{{ label: 'Shows', data: D.schedule.times.map(t => t.count),
                   backgroundColor: '#7c3aed' }}],
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }},
                scales: {{ y: {{ beginAtZero: true }} }} }},
  }});
}}

if (D.tm_seat && D.tm_seat.extra) {{
  const x = D.tm_seat.extra;

  // Time-of-day bar chart
  new Chart(document.getElementById('todChart'), {{
    type: 'bar',
    data: {{
      labels: x.tod_labels.map(t => {{
        const h = parseInt(t.slice(0,2));
        return (h<12?h:(h-12||12)) + (h<12?'am':'pm');
      }}),
      datasets: [{{
        label: 'Avg best-available ($)',
        data: x.tod_avgs,
        backgroundColor: '#2563eb',
      }}],
    }},
    options: {{
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
        afterLabel: ctx => x.tod_counts[ctx.dataIndex] + ' shows'
      }} }} }},
      scales: {{ y: {{ beginAtZero: false, title: {{ display: true, text: '$' }} }} }},
    }},
  }});

  // Weekday bar chart
  new Chart(document.getElementById('wdChart'), {{
    type: 'bar',
    data: {{
      labels: x.wd_labels,
      datasets: [{{
        label: 'Avg best-available ($)',
        data: x.wd_avgs,
        backgroundColor: '#059669',
      }}],
    }},
    options: {{
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
        afterLabel: ctx => x.wd_counts[ctx.dataIndex] + ' shows'
      }} }} }},
      scales: {{ y: {{ beginAtZero: false, title: {{ display: true, text: '$' }} }} }},
    }},
  }});

  // Price histogram
  new Chart(document.getElementById('priceHistChart'), {{
    type: 'bar',
    data: {{
      labels: x.hist_labels,
      datasets: [{{
        label: '# quickpick offers in bucket',
        data: x.hist_data,
        backgroundColor: '#7c3aed',
      }}],
    }},
    options: {{
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        y: {{ beginAtZero: true, title: {{ display: true, text: '# offers' }} }},
        x: {{ title: {{ display: true, text: 'Price bucket' }} }},
      }},
    }},
  }});
}}

if (D.tm_seat && D.tm_seat.labels && D.tm_seat.labels.length) {{
  new Chart(document.getElementById('seatPriceChart'), {{
    type: 'line',
    data: {{
      labels: D.tm_seat.labels,
      datasets: [
        {{
          label: 'Face max ($)',
          data: D.tm_seat.face_max,
          borderColor: '#dc2626',
          backgroundColor: 'rgba(220,38,38,0.05)',
          borderWidth: 2,
          tension: 0.1,
          pointRadius: 4,
          fill: false,
          spanGaps: true,
        }},
        {{
          label: 'Best available ($)',
          data: D.tm_seat.best_avail,
          borderColor: '#2563eb',
          backgroundColor: 'rgba(37,99,235,0.1)',
          borderWidth: 2,
          tension: 0.1,
          pointRadius: 5,
          fill: false,
          spanGaps: true,
        }},
        {{
          label: 'Face min ($)',
          data: D.tm_seat.face_min,
          borderColor: '#888',
          backgroundColor: 'transparent',
          borderWidth: 1,
          borderDash: [4, 4],
          tension: 0.1,
          pointRadius: 3,
          fill: false,
          spanGaps: true,
        }},
        {{
          label: 'Likely sellout',
          data: D.tm_seat.sellout,
          borderColor: 'transparent',
          backgroundColor: '#dc2626',
          showLine: false,
          pointRadius: 8,
          pointStyle: 'crossRot',  // an X marker
          pointBorderWidth: 3,
          pointBorderColor: '#dc2626',
        }},
      ],
    }},
    options: {{
      plugins: {{ legend: {{ position: 'bottom' }} }},
      scales: {{
        y: {{ beginAtZero: false, title: {{ display: true, text: 'Price ($)' }} }},
        x: {{ ticks: {{ maxRotation: 45, minRotation: 30 }} }},
      }},
    }},
  }});
}}

if (D.trends && D.trends.series && D.trends.summary) {{
  const summary = D.trends.summary;
  // 9-color palette (one per keyword)
  const colors = ['#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed',
                  '#0891b2', '#db2777', '#65a30d', '#a16207'];

  // -------- Bar chart: current 4w avg per keyword, ranked --------
  new Chart(document.getElementById('trendsBarChart'), {{
    type: 'bar',
    data: {{
      labels: summary.map(s => s.kw),
      datasets: [{{
        label: 'Last 4w avg RSV',
        data: summary.map(s => s.last4),
        backgroundColor: summary.map(s => s.delta >= 0 ? '#059669' : '#dc2626'),
      }}],
    }},
    options: {{
      indexAxis: 'y',
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{ beginAtZero: true, title: {{ display: true, text: 'RSV (0-100)' }} }},
      }},
    }},
  }});

  // -------- Main 12-month line chart, all 9 keywords --------
  const kws = summary.map(s => s.kw);  // ordered by current interest
  const labels = D.trends.series[kws[0]].weeks;
  new Chart(document.getElementById('trendsChart'), {{
    type: 'line',
    data: {{
      labels: labels,
      datasets: kws.map((kw, i) => ({{
        label: kw,
        data: D.trends.series[kw].rsv,
        borderColor: colors[i % colors.length],
        backgroundColor: 'transparent',
        tension: 0.2,
        pointRadius: 0,
        borderWidth: 2,
      }})),
    }},
    options: {{
      plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }} }},
      scales: {{
        y: {{ beginAtZero: true, title: {{ display: true, text: 'RSV (0-100)' }} }},
        x: {{ ticks: {{ maxTicksLimit: 12 }} }},
      }},
    }},
  }});

  // -------- Sparkline grid, one per keyword --------
  kws.forEach((kw, i) => {{
    const canvas = document.getElementById('sparkline-' + i);
    if (!canvas) return;
    const rsv = D.trends.series[kw].rsv;
    new Chart(canvas, {{
      type: 'line',
      data: {{
        labels: rsv.map((_, j) => j),
        datasets: [{{
          data: rsv,
          borderColor: colors[i % colors.length],
          backgroundColor: 'transparent',
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 1.5,
        }}],
      }},
      options: {{
        plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }},
        scales: {{
          y: {{ display: false }},
          x: {{ display: false }},
        }},
        elements: {{ point: {{ radius: 0 }} }},
        maintainAspectRatio: false,
      }},
    }});
  }});
}}
</script>
</body>
</html>
"""

with open(OUT, 'w') as f:
    f.write(html)

print(f'Wrote {OUT}  ({os.path.getsize(OUT):,} bytes)')
print(f'Open in browser: file://{OUT}')
