#!/usr/bin/env python3
"""Gunicorn config for Beta Client."""
import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('CLIENT_PORT', '23400')}"
workers = min(multiprocessing.cpu_count(), 4)
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
accesslog = "-"
errorlog = "-"
loglevel = "info"
