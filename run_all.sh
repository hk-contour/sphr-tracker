#!/bin/bash
# Run all pulls + regenerate dashboard. Intended for a daily cron.
set -euo pipefail
cd "$(dirname "$0")"

echo "===== sphr-tracker daily run @ $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="

echo ""
echo "[1/4] SeatGeek schedule (cheap, every run is fine)"
bash pulls/seatgeek.sh

echo ""
echo "[2/4] Google Trends"
python3 pulls/pytrends_pull.py

echo ""
echo "[3/4] TM Discovery"
python3 pulls/tm_discovery.py

echo ""
echo "[4/4] TM Seatmap (ScrapingBee, 30-day forward window)"
python3 pulls/tm_seatmap.py --days 30

echo ""
echo "Building dashboard..."
python3 dashboard.py

echo ""
echo "Done @ $(date -u +%Y-%m-%dT%H:%M:%SZ)"
