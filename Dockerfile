FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    unzip \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    fonts-liberation \
    tor \
    xvfb \
    x11-utils \
    x11-xserver-utils \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz | tar -xz -C /usr/local/bin/

RUN chromium --version && chromedriver --version && ngrok version || true

WORKDIR /app
COPY requirements.txt client-requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r client-requirements.txt
COPY . .
RUN chmod +x entrypoint.sh
RUN mkdir -p /app/img /app/static

EXPOSE 8000 23400

ENV MALLOC_TRIM_THRESHOLD_=65536
ENV MALLOC_MMAP_THRESHOLD_=65536
ENV MALLOC_MMAP_MAX_=0
ENV BROWSER_HEADLESS=false
ENV USE_TOR=false
ENV LOCAL_UI_HOST=0.0.0.0
ENV LOCAL_UI_PORT=23400

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
