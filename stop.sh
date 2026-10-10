#!/usr/bin/env bash
# Stop the HalalReady rig: the MCP server and the backend it spawned.
set -uo pipefail
cd "$(dirname "$0")"

if [ -f mcp_server.pid ]; then
    PID="$(cat mcp_server.pid)"
    if kill "$PID" 2>/dev/null; then
        echo "Stopped MCP server (pid $PID)."
    else
        echo "MCP server pid $PID was not running."
    fi
    rm -f mcp_server.pid
else
    echo "No mcp_server.pid — was it started with ./start.sh?"
fi

# The backend runs detached, so find it by the port it listens on.
BACKEND_PID=$(netstat -ano 2>/dev/null | grep ":8000 " | grep -i LISTENING | awk '{print $5}' | head -1)
if [ -n "${BACKEND_PID:-}" ]; then
    if taskkill //F //PID "$BACKEND_PID" >/dev/null 2>&1; then
        echo "Stopped backend (pid $BACKEND_PID)."
    else
        echo "Could not stop backend pid $BACKEND_PID — stop it by hand."
    fi
else
    echo "Nothing listening on :8000."
fi
