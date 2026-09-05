#!/bin/bash
# Beta Client startup script
# Uses gunicorn in production, uvicorn in development

set -e

HOST="${CLIENT_HOST:-0.0.0.0}"
PORT="${CLIENT_PORT:-23400}"
WORKERS="${CLIENT_WORKERS:-2}"

if [ "$ENV" = "production" ] || [ -f "/app/Dockerfile" ]; then
    echo "Starting with gunicorn (production)..."
    exec gunicorn client.ui.app:create_app \
        --config client/gunicorn.conf.py \
        --bind "$HOST:$PORT" \
        --workers "$WORKERS"
else
    echo "Starting with uvicorn (development)..."
    exec python -m client.main
fi
