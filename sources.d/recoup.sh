#!/usr/bin/env bash
# el event source: recoup job listener
# Usage: recoup.sh [port] [bot_id]
# Starts recoup server, waits for one job, outputs result as JSON, exits.

PORT="${1:-9402}"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

exec python3 "$SCRIPT_DIR/scripts/recoup-server.py" --port "$PORT"
