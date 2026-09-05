#!/bin/bash
set -e

# Start Tor in background if USE_TOR is enabled
if [ "$USE_TOR" = "true" ] || [ "$USE_TOR" = "1" ]; then
    echo "[entrypoint] Starting Tor..."
    mkdir -p /tmp/tor_data

    cat > /tmp/torrc <<EOF
SocksPort 9050
DataDirectory /tmp/tor_data
Log notice stdout
EOF

    if [ -n "$TOR_BRIDGES" ]; then
        echo "[entrypoint] Configuring Tor bridges..."
        echo "UseBridges 1" >> /tmp/torrc
        echo "$TOR_BRIDGES" | while IFS= read -r line; do
            [ -n "$line" ] && echo "Bridge $line" >> /tmp/torrc
        done
    fi

    tor -f /tmp/torrc &
    TOR_PID=$!
    echo "[entrypoint] Tor started (PID=$TOR_PID), waiting for bootstrap..."

    for i in $(seq 1 60); do
        if curl -s --socks5 127.0.0.1:9050 --connect-timeout 2 https://check.torproject.org/api/ip > /dev/null 2>&1; then
            echo "[entrypoint] Tor bootstrap complete"
            break
        fi
        sleep 1
    done
fi

# Start Backend (FastAPI)
echo "[entrypoint] Starting Backend on port 8000..."
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 60 &
BACKEND_PID=$!
echo "[entrypoint] Backend started (PID=$BACKEND_PID)"

# Start Client (Flask Web UI)
echo "[entrypoint] Starting Client Web UI on port 23400..."
python -m client &
CLIENT_PID=$!
echo "[entrypoint] Client started (PID=$CLIENT_PID)"

# Start ngrok if token is provided
if [ -n "$NGROK_AUTH_TOKEN" ]; then
    echo "[entrypoint] Starting ngrok tunnel..."
    ngrok config add-authtoken "$NGROK_AUTH_TOKEN" 2>/dev/null || true
    ngrok http 23400 --log=stdout --log-format=json &
    NGROK_PID=$!
    echo "[entrypoint] ngrok started (PID=$NGROK_PID), tunneling port 23400"

    # Wait for ngrok to establish tunnel and print URL
    for i in $(seq 1 30); do
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tunnels = data.get('tunnels', [])
    for t in tunnels:
        if t.get('proto') == 'https':
            print(t.get('public_url', ''))
            break
except:
    pass
" 2>/dev/null)
        if [ -n "$NGROK_URL" ]; then
            echo "[entrypoint] ========================================"
            echo "[entrypoint] ngrok URL: $NGROK_URL"
            echo "[entrypoint] Client UI available at: $NGROK_URL"
            echo "[entrypoint] ========================================"
            break
        fi
        sleep 1
    done

    if [ -z "$NGROK_URL" ]; then
        echo "[entrypoint] WARNING: Could not retrieve ngrok URL yet. Check ngrok logs."
    fi
else
    echo "[entrypoint] NGROK_AUTH_TOKEN not set, skipping ngrok tunnel."
    echo "[entrypoint] Client UI available at http://localhost:23400 (local only)"
fi

# Wait for all background processes
echo "[entrypoint] All services started. Waiting..."
wait
