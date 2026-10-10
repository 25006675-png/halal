#!/usr/bin/env bash
# Start the HalalReady rig detached from this terminal.
#
# The MCP server starts the backend itself if it is not already running, so
# this launches exactly one thing. Safe to run twice.
#
#   ./start.sh
#   MCP URL   -> http://127.0.0.1:8100/mcp
#   live log  -> http://127.0.0.1:8000/events/view
#   stop with -> ./stop.sh
set -euo pipefail
cd "$(dirname "$0")"

PY="./.venv/Scripts/python.exe"
[ -f "$PY" ] || PY="python"

if [ -f mcp_server.pid ] && kill -0 "$(cat mcp_server.pid)" 2>/dev/null; then
    echo "Already running (pid $(cat mcp_server.pid)). Nothing to do."
    echo "  MCP URL   http://127.0.0.1:8100/mcp"
    echo "  live log  http://127.0.0.1:8000/events/view"
    exit 0
fi

nohup "$PY" mcp/server.py > mcp_server.log 2>&1 &
echo $! > mcp_server.pid
disown 2>/dev/null || true

# Give the MCP server a moment to boot and to pull the backend up with it.
for _ in $(seq 1 40); do
    if curl -s -m 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

echo "Started (pid $(cat mcp_server.pid))."
echo "  MCP URL   http://127.0.0.1:8100/mcp"
echo "  live log  http://127.0.0.1:8000/events/view"
echo "  logs      mcp_server.log, backend/backend.log"
echo "Stop with ./stop.sh"
