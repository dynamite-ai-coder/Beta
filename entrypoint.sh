#!/bin/bash
set -e

# Start Tor in background if USE_TOR is enabled
if [ "$USE_TOR" = "true" ] || [ "$USE_TOR" = "1" ]; then
    echo "[entrypoint] Starting Tor..."
    mkdir -p /tmp/tor_data

    # Write torrc
    cat > /tmp/torrc <<EOF
SocksPort 9050
DataDirectory /tmp/tor_data
Log notice stdout
EOF

    # Add bridges if configured
    if [ -n "$TOR_BRIDGES" ]; then
        echo "[entrypoint] Configuring Tor bridges..."
        echo "UseBridges 1" >> /tmp/torrc
        echo "$TOR_BRIDGES" | while IFS= read -r line; do
            [ -n "$line" ] && echo "Bridge $line" >> /tmp/torrc
        done
    fi

    # Start tor daemon
    tor -f /tmp/torrc &
    TOR_PID=$!
    echo "[entrypoint] Tor started (PID=$TOR_PID), waiting for bootstrap..."

    # Wait for SOCKS port to be ready (max 60s)
    for i in $(seq 1 60); do
        if curl -s --socks5 127.0.0.1:9050 --connect-timeout 2 https://check.torproject.org/api/ip > /dev/null 2>&1; then
            echo "[entrypoint] Tor bootstrap complete"
            break
        fi
        sleep 1
    done
fi

exec "$@"
