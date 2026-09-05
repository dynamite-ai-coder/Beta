#!/bin/bash
set -e

echo "[entrypoint] Beta starting..."
echo "[entrypoint] LOCAL_UI_HOST=${LOCAL_UI_HOST:-0.0.0.0}"
echo "[entrypoint] BACKEND_URL=${BACKEND_URL:-http://localhost:8000}"
echo "[entrypoint] NGROK_AUTH_TOKEN=${NGROK_AUTH_TOKEN:-(not set)}"

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

# Start ngrok tunnel if token provided
if [ -n "$NGROK_AUTH_TOKEN" ] && [ "$NGROK_AUTH_TOKEN" != "" ]; then
    echo "[entrypoint] Starting ngrok tunnel on :23400..."
    ngrok config add-authtoken "$NGROK_AUTH_TOKEN" 2>/dev/null || true
    ngrok http 23400 --log=stdout --log-format=json &
    NGROK_PID=$!

    for i in $(seq 1 30); do
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for t in data.get('tunnels', []):
        if t.get('proto') == 'https':
            print(t['public_url'])
            break
except:
    pass
" 2>/dev/null)
        if [ -n "$NGROK_URL" ]; then
            echo ""
            echo "========================================"
            echo "  ngrok URL: $NGROK_URL"
            echo "  Client UI: $NGROK_URL"
            echo "========================================"
            break
        fi
        sleep 1
    done
    [ -z "$NGROK_URL" ] && echo "[entrypoint] WARNING: ngrok URL not ready yet"
else
    echo "[entrypoint] NGROK_AUTH_TOKEN not set, no tunnel"
fi

echo "[entrypoint] All services started. Backend=$BACKEND_PID Client=$CLIENT_PID"
wait
