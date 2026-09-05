#!/bin/bash
set -e

echo "[entrypoint] Beta starting..."
echo "[entrypoint] LOCAL_UI_HOST=${LOCAL_UI_HOST:-0.0.0.0}"
echo "[entrypoint] BACKEND_URL=${BACKEND_URL:-http://localhost:8000}"

export CLIENT_URL="${CLIENT_URL:-http://localhost:23400}"

# Start Tor if enabled
if [ "$USE_TOR" = "true" ] || [ "$USE_TOR" = "1" ]; then
    echo "[entrypoint] Starting Tor..."
    mkdir -p /tmp/tor_data
    cat > /tmp/torrc <<EOF
SocksPort 9050
DataDirectory /tmp/tor_data
Log notice stdout
EOF
    if [ -n "$TOR_BRIDGES" ]; then
        echo "UseBridges 1" >> /tmp/torrc
        echo "$TOR_BRIDGES" | while IFS= read -r line; do
            [ -n "$line" ] && echo "Bridge $line" >> /tmp/torrc
        done
    fi
    tor -f /tmp/torrc &
    for i in $(seq 1 60); do
        if curl -s --socks5 127.0.0.1:9050 --connect-timeout 2 https://check.torproject.org/api/ip > /dev/null 2>&1; then
            echo "[entrypoint] Tor bootstrap complete"
            break
        fi
        sleep 1
    done
fi

# Start Backend
echo "[entrypoint] Starting Backend on :8000..."
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 60 &
BACKEND_PID=$!

# Wait for backend to be ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "[entrypoint] Backend ready"
        break
    fi
    sleep 1
done

# Start Client
echo "[entrypoint] Starting Client on :23400..."
python -m client &
CLIENT_PID=$!

# Wait for client to be ready
for i in $(seq 1 15); do
    if curl -sf http://localhost:23400/api/status > /dev/null 2>&1; then
        echo "[entrypoint] Client ready"
        break
    fi
    sleep 1
done

echo ""
echo "========================================"
echo "  Client UI: <RENDER_URL>/ui/"
echo "  Backend API: <RENDER_URL>/docs"
echo "========================================"

echo "[entrypoint] All services started. Backend=$BACKEND_PID Client=$CLIENT_PID"
wait
