#!/bin/bash
set -e

cd /public/Beta

echo "[start] Killing existing processes..."
pkill -f uvicorn 2>/dev/null || true
pkill -f "python -m client" 2>/dev/null || true
pkill -f ngrok 2>/dev/null || true
pkill -f groq_service 2>/dev/null || true
sleep 2

echo "[start] Starting Groq Accelerator..."
nohup python3 groq_service.py > /tmp/groq.log 2>&1 &
echo "  PID: $!"

echo "[start] Starting Backend..."
nohup uvicorn backend.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 60 > /tmp/backend.log 2>&1 &
echo "  PID: $!"

echo "[start] Waiting for backend..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "  Backend ready"
        break
    fi
    sleep 1
done

echo "[start] Starting Client..."
nohup python -m client > /tmp/client.log 2>&1 &
echo "  PID: $!"

echo "[start] Waiting for client..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:23400/api/status > /dev/null 2>&1; then
        echo "  Client ready"
        break
    fi
    sleep 1
done

echo "[start] Starting ngrok..."
nohup ngrok http 23400 --url https://idealize-nutty-enhance.ngrok-free.dev --log=stdout --log-format=json > /tmp/ngrok.log 2>&1 &
echo "  PID: $!"

echo "[start] Waiting for ngrok..."
sleep 5

echo ""
echo "========================================"
echo "  All services started!"
echo "  Backend: http://localhost:8000"
echo "  Client:  http://localhost:23400"
echo "  ngrok:   https://idealize-nutty-enhance.ngrok-free.dev"
echo "========================================"

echo "[start] Testing..."
curl -sf http://localhost:8000/health && echo " [OK] Backend" || echo " [FAIL] Backend"
curl -sf http://localhost:23400/api/status | python3 -m json.tool && echo " [OK] Client" || echo " [FAIL] Client"
curl -sf https://idealize-nutty-enhance.ngrok-free.dev/api/status | python3 -m json.tool && echo " [OK] ngrok" || echo " [FAIL] ngrok"
