#!/usr/bin/env python3
"""
Generate dashboard.html from whatever CSVs exist in data/.

Reads:
  data/seatgeek_schedule.csv     (required)
  data/pytrends_history.csv      (optional)
  data/tm_discovery_history.csv  (optional)
  data/tripadvisor_reviews.csv   (optional)

Writes:
  dashboard.html — single-file static report with Chart.js via CDN.
"""
import os, csv, json
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = f'{ROOT}/data'
OUT = f'{ROOT}/dashboard.html'

def read_csv(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return list(csv.DictReader(f))

schedule = read_csv(f'{DATA}/seatgeek_schedule.csv')
trends = read_csv(f'{DATA}/pytrends_history.csv')
tm_disc = read_csv(f'{DATA}/tm_discovery_history.csv')
tm_seat = read_csv(f'{DATA}/tm_seatmap_history.csv')
reviews = read_csv(f'{DATA}/tripadvisor_reviews.csv')

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
        by_kw[r['keyword']].append((r['week_start'], int(r['rsv'])))
    series = {}
    for kw, pts in by_kw.items():
        pts.sort()
        series[kw] = {
            'weeks': [p[0] for p in pts],
            'rsv': [p[1] for p in pts],
        }
    # Compute the headline 4w vs prior 4w delta for each keyword
    summary = []
    for kw, pts in by_kw.items():
        pts.sort()
        vals = [p[1] for p in pts]
        if len(vals) >= 8:
            last4, prev4 = sum(vals[-4:])/4, sum(vals[-8:-4])/4
            delta = (last4 - prev4) / prev4 * 100 if prev4 else 0
            summary.append({'kw': kw, 'last4': last4, 'prev4': prev4, 'delta': delta})
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

<div class="panel">
  <div class="panel-title">1 · Schedule overview (SeatGeek)</div>
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

html += '</div>\n\n<div class="panel"><div class="panel-title">2 · Search interest (Google Trends)</div>'

if trends_data:
    html += '<table><tr><th>Keyword</th><th style="text-align:right;">Prev 4w avg</th><th style="text-align:right;">Last 4w avg</th><th style="text-align:right;">Δ</th></tr>'
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
    html += '<h3>Weekly RSV, last 12 months</h3><div class="chart-container"><canvas id="trendsChart"></canvas></div>'
else:
    html += '<div class="pending">No trends data — run pulls/pytrends_pull.py</div>'

html += '</div>\n\n<div class="panel"><div class="panel-title">3 · Ticketmaster Discovery (status + sales windows)</div>'
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

tm_seat_chart = None
if tm_seat:
    # Latest poll per event, filtered to a sensible window: yesterday → +30 days
    from datetime import timedelta as _td
    today_d = datetime.now().date()
    window_start = (today_d - _td(days=1)).isoformat()
    window_end = (today_d + _td(days=30)).isoformat()

    by_event = defaultdict(list)
    for r in tm_seat:
        if window_start <= r['event_date'] <= window_end:
            by_event[(r['event_date'], r['event_time'])].append(r)

    rows_per_event = []
    for key, rows in by_event.items():
        latest_ts = max(r['poll_ts_utc'] for r in rows)
        latest = [r for r in rows if r['poll_ts_utc'] == latest_ts]
        prices = [float(r['price']) for r in latest if r['price']]
        rows_per_event.append({
            'date': key[0],
            'time': key[1][:5],
            'datetime_label': f"{key[0]} {key[1][:5]}",
            'face_min': float(latest[0]['face_price_min']) if latest[0]['face_price_min'] else None,
            'face_max': float(latest[0]['face_price_max']) if latest[0]['face_price_max'] else None,
            'best_avail': min(prices) if prices else None,
            'qp_count': len(latest),
        })
    rows_per_event.sort(key=lambda r: (r['date'], r['time']))

    # Coverage stats — how many days in window have at least one scrape?
    scraped_days = sorted({r['date'] for r in rows_per_event})
    total_days = 31  # window_start → window_end inclusive
    coverage_pct = len(scraped_days) / total_days * 100 if total_days else 0

    avg_best = sum(r['best_avail'] for r in rows_per_event if r['best_avail']) / max(1, len([r for r in rows_per_event if r['best_avail']]))
    min_best = min((r['best_avail'] for r in rows_per_event if r['best_avail']), default=0)
    max_best = max((r['best_avail'] for r in rows_per_event if r['best_avail']), default=0)

    tm_seat_chart = {
        'labels': [r['datetime_label'] for r in rows_per_event],
        'best_avail': [r['best_avail'] for r in rows_per_event],
        'face_max': [r['face_max'] for r in rows_per_event],
        'face_min': [r['face_min'] for r in rows_per_event],
    }

    html += f"""
<div class="panel">
  <div class="panel-title">3b · TM seatmap — best available + face price (next 30 days)</div>
  <div class="meta">Scraped via ScrapingBee stealth proxy. Each render returns 40 "best available" quickpick offers per show. Window: {window_start} → {window_end}.</div>
  <div class="stat-row">
    <div class="stat">
      <div class="stat-label">Shows scraped in window</div>
      <div class="stat-value">{len(rows_per_event)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Days w/ data</div>
      <div class="stat-value">{len(scraped_days)} / {total_days}</div>
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
  <h3>Price over the 30-day forward window</h3>
  <div class="chart-container"><canvas id="seatPriceChart"></canvas></div>
  <div class="meta" style="margin-top:8px;">
    Each marker = one scraped showtime. <span style="color:#2563eb;">●</span> best available ·
    <span style="color:#dc2626;">●</span> face max ·
    <span style="color:#888;">●</span> face min.
    Gaps in the line = days not yet scraped — chart fills in as the daily ScrapingBee batch runs.
  </div>
</div>"""

html += '\n\n<div class="panel"><div class="panel-title">4 · Reviews (TripAdvisor)</div>'
if reviews:
    html += '<div class="pending">TODO: render reviews panel</div>'
else:
    html += """<div class="pending">
      Not yet built. ScrapingBee is now in place (same path that unlocks TM) — TripAdvisor scrape
      can be wired in next using <code>stealth_proxy=true</code> against the Sphere attraction page.
    </div>"""
html += '</div>'

# ---------- JS for charts ----------
chart_data = {
    'schedule': sched_data,
    'trends': trends_data,
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

if (D.trends && D.trends.series) {{
  const kws = Object.keys(D.trends.series);
  const colors = ['#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed'];
  const firstKw = kws[0];
  const labels = D.trends.series[firstKw].weeks;
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
      plugins: {{ legend: {{ position: 'bottom' }} }},
      scales: {{
        y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'RSV (0-100)' }} }},
        x: {{ ticks: {{ maxTicksLimit: 12 }} }},
      }},
    }},
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
