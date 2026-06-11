#!/bin/bash
# Pull the full Wizard of Oz at Sphere schedule from SeatGeek.
# Writes paged JSON to ../data/seatgeek_pages/, then flattens to ../data/seatgeek_schedule.csv
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a; source "$ROOT/.env"; set +a

VENUE_ID=521212
PAGE=1
PAGES_DIR="$ROOT/data/seatgeek_pages"
rm -rf "$PAGES_DIR" && mkdir -p "$PAGES_DIR"

while true; do
  echo "Fetching page $PAGE..."
  curl -sS --max-time 30 --retry 3 \
    "https://api.seatgeek.com/2/events?venue.id=${VENUE_ID}&q=wizard+of+oz&per_page=100&page=${PAGE}&client_id=${SEATGEEK_CLIENT_ID}" \
    > "$PAGES_DIR/page_${PAGE}.json"
  COUNT=$(python3 -c "import json;print(len(json.load(open('$PAGES_DIR/page_${PAGE}.json'))['events']))")
  TOTAL=$(python3 -c "import json;print(json.load(open('$PAGES_DIR/page_${PAGE}.json'))['meta']['total'])")
  echo "  got $COUNT events (total: $TOTAL)"
  if [ "$COUNT" -lt 100 ]; then break; fi
  PAGE=$((PAGE+1))
  sleep 0.3
done

echo ""
echo "Flattening to CSV..."
python3 "$ROOT/pulls/seatgeek_flatten.py"
