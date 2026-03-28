#!/usr/bin/env bash
set -e

PORT=8000

# Kill any process currently occupying the port
if lsof -ti:$PORT &>/dev/null; then
  echo "→ Killing existing process on port $PORT..."
  lsof -ti:$PORT | xargs kill -9
  sleep 0.5
fi

echo "→ Starting AI Sales Agent on http://localhost:$PORT"
cd "$(dirname "$0")"
exec uv run uvicorn api:app --reload --port $PORT
