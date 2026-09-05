#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# Beta Browser AI - Termux Setup Script
# One-command install for Android/Termux
# Updated: 2026
# ============================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║     Beta Browser AI - Termux Setup        ║"
echo "  ║     Updated: 2026                         ║"
echo "  ╚═══════════════════════════════════════════╝"
echo -e "${NC}"

# --- Step 1: System packages ---
echo -e "${YELLOW}[1/8] Installing system packages...${NC}"
pkg update -y 2>/dev/null || apt update -y
pkg install -y python git curl wget ffmpeg libjpeg-turbo libpng freetype libffi openssl binutils 2>/dev/null || \
apt install -y python git curl wget ffmpeg libjpeg-turbo libpng freetype libffi openssl binutils
echo -e "${GREEN}  OK${NC}"

# --- Step 2: Python pip upgrade ---
echo -e "${YELLOW}[2/8] Upgrading pip...${NC}"
pip install --upgrade pip setuptools wheel 2>/dev/null
echo -e "${GREEN}  OK${NC}"

# --- Step 3: Clone / update repo ---
echo -e "${YELLOW}[3/8] Cloning repository...${NC}"
REPO_DIR="$HOME/beta-browser"
if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"
    git pull origin main 2>/dev/null || echo "  Using existing repo"
else
    git clone https://github.com/dynamite-ai-coder/Beta.git "$REPO_DIR" 2>/dev/null || {
        echo -e "${RED}  Clone failed. Check your internet connection.${NC}"
        exit 1
    }
    cd "$REPO_DIR"
fi
echo -e "${GREEN}  OK: $REPO_DIR${NC}"

# --- Step 4: Install Python dependencies ---
echo -e "${YELLOW}[4/8] Installing Python packages...${NC}"
pip install -r client-requirements.txt 2>/dev/null
echo -e "${GREEN}  OK${NC}"

# --- Step 5: Install matplotlib (for charts/plots) ---
echo -e "${YELLOW}[5/8] Installing matplotlib...${NC}"
pip install matplotlib 2>/dev/null
echo -e "${GREEN}  OK${NC}"

# --- Step 6: Configure .env ---
echo -e "${YELLOW}[6/8] Configuring environment...${NC}"
if [ ! -f .env ] || [ ! -s .env ]; then
    cp .env.example .env 2>/dev/null || cat > .env << 'ENVEOF'
# AI / Groq Free Tier
AI_API_KEY=
AI_MODEL=openai/gpt-oss-120b
AI_BASE_URL=https://api.groq.com/openai/v1
AI_PROVIDER=groq

# Groq Multi-Key Accelerator (4 keys = ~120 RPM)
GROQ_KEYS=

# Virtual AI API
BETA_API_KEY=beta_api_token_2026_secure
VIRTUAL_MODEL_NAME=beta-virtual-ai

# API Security
API_AUTH_TOKEN=beta_api_token_2026_secure

# Backend
BACKEND_URL=https://beta-fmp9.onrender.com

# Timeouts
BROWSER_SESSION_TIMEOUT=600
TASK_TIMEOUT=300

# Browser Settings
HEADLESS=true
BROWSER_ENGINE=selenium

# Preview
PREVIEW_ENABLED=true
PREVIEW_TOKEN_SECRET=change-me-in-production

# Rate Limiting
RATE_LIMIT_PER_MINUTE=10

# Debug
DEBUG=false

# Proxy (optional)
PROXY_ENABLED=false
PROXY_APIKEY=
PROXY_SECRET=
PROXY_URL=

# Tor (optional anonymity)
USE_TOR=false
TOR_BRIDGES=
ENVEOF
    echo -e "${GREEN}  Created .env${NC}"
else
    echo -e "${GREEN}  .env exists${NC}"
fi

# --- Step 7: Configure Termux API for sensors ---
echo -e "${YELLOW}[7/8] Checking Termux API...${NC}"
if command -v termux-notification &> /dev/null; then
    echo -e "${GREEN}  Termux API available${NC}"
else
    echo -e "${YELLOW}  Install 'Termux:API' app for extra features (optional)${NC}"
fi

# --- Step 8: Detect environment ---
echo -e "${YELLOW}[8/8] Detecting environment...${NC}"
RAM_MB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print int($2/1024)}')
echo -e "${GREEN}  RAM: ${RAM_MB:-unknown}MB${NC}"

if [ -n "$TERMUX_VERSION" ] || [ -d "/data/data/com.termux" ]; then
    echo -e "${GREEN}  Platform: Termux/Android${NC}"
else
    echo -e "${GREEN}  Platform: Linux${NC}"
fi

echo ""
echo -e "${CYAN}"
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║           Setup Complete!                  ║"
echo "  ╚═══════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
echo -e "${YELLOW}Quick start:${NC}"
echo -e "  cd $REPO_DIR"
echo -e "  python -m client"
echo ""
echo -e "${YELLOW}Then open in browser:${NC}"
echo -e "  http://127.0.0.1:23400"
echo ""
echo -e "${YELLOW}Edit .env to add your API keys:${NC}"
echo -e "  nano $REPO_DIR/.env"
echo ""
echo -e "${YELLOW}Groq Accelerator (4 keys, ~120 RPM):${NC}"
echo -e "  GROQ_KEYS=key1,key2,key3,key4 python3 groq_accelerator.py"
echo ""
