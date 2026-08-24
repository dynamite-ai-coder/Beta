# Browser Automation API

Authorized browser testing and QA automation tool with AI-powered element identification.

## Architecture

```
GitHub → Render (Docker)
├── FastAPI Backend (Python 3.11+)
│   ├── Selenium-controlled Chromium
│   ├── AI Element Identification (Groq)
│   ├── Task Management
│   └── Browser Preview/Streaming
└── CLI Client (Python)
```

## Project Structure

```
backend/
├── main.py              # FastAPI application
├── config.py            # Configuration management
├── api/
│   └── routes.py        # API endpoints
├── browser/
│   ├── driver.py        # Selenium browser control
│   └── agent.py         # Browser automation agent
├── ai/
│   ├── provider.py      # AI/Groq provider
│   └── identifier.py    # Element identification
├── tasks/
│   └── manager.py       # Task lifecycle management
├── security/
│   └── auth.py          # Authentication & security
├── streaming/
│   └── preview.py       # Browser preview streaming
├── models/
│   └── schemas.py       # Pydantic models
└── utils/
client/
├── main.py              # CLI entry point
├── api_client.py        # API client
├── ui.py                # Terminal UI
└── config.py            # Client configuration
tests/
├── test_backend.py      # Backend unit tests
├── test_api.py          # API integration tests
└── mock_login.html      # Mock login page for testing
```

## Local Setup

```bash
# Clone the repository
git clone https://github.com/dynamite-ai-coder/Beta.git
cd Beta

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp .env.example .env
# Edit .env with your GROQ_API_KEY

# Start the backend
uvicorn backend.main:app --reload

# In another terminal, start the client
python -m client.main
```

## Docker Setup

```bash
# Build the image
docker build -t browser-automation .

# Run the container
docker run -p 8000:8000 \
  -e GROQ_API_KEY=your_key \
  -e API_AUTH_TOKEN=your_token \
  browser-automation
```

## Render Deployment

1. Create a GitHub repository and push this project
2. Go to [render.com](https://render.com) and create a new Web Service
3. Connect your GitHub repository
4. Configure:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
5. Set environment variables in Render dashboard
6. Enable auto-deploy on push

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GROQ_API_KEY` | Groq API key for AI | - |
| `GROQ_MODEL` | Groq model name | `llama-3.1-8b-instant` |
| `API_AUTH_TOKEN` | API authentication token | - |
| `ALLOWED_DOMAINS` | Comma-separated allowed domains | - |
| `BROWSER_SESSION_TIMEOUT` | Browser session timeout (s) | `600` |
| `TASK_TIMEOUT` | Task timeout (s) | `300` |
| `HEADLESS` | Run browser headless | `true` |
| `RATE_LIMIT_PER_MINUTE` | Rate limit per IP | `30` |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/task` | Create automation task |
| GET | `/api/v1/task/{id}` | Get task status |
| GET | `/api/v1/task/{id}/events` | Get task events |
| GET | `/api/v1/task/{id}/preview` | Browser preview stream |
| POST | `/api/v1/task/{id}/manual-action` | Continue after manual action |
| POST | `/api/v1/task/{id}/stop` | Stop task |

## Client Usage

```bash
python -m client.main
```

The client will:
1. Connect to the backend
2. Ask for target URL, username, and password
3. Create and monitor an automation task
4. Display progress and results

## Security Model

- API authentication via Bearer tokens
- URL allowlisting for production
- SSRF protection (blocks localhost, private networks, metadata endpoints)
- Password redaction in logs
- Rate limiting per IP
- Browser session timeout
- No credential storage
- Screenshot filename sanitization

## CAPTCHA / Manual Intervention

When CAPTCHA or anti-bot protection is detected:
1. Automated interaction stops
2. Task state changes to `WAITING_FOR_MANUAL_ACTION`
3. Browser session stays alive
4. Operator completes challenge manually
5. Operator resumes via API or client

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_backend.py -v

# Run with coverage
pytest tests/ --cov=backend --cov-report=html
```

## Limitations

- Requires Chrome/Chromium installed
- Groq API key required for AI element identification
- Browser preview requires direct HTTP access (may not work through some proxies)
- Headless mode only in production
- No persistent task storage (in-memory)

## Recommended Next Steps

- Add PostgreSQL for persistent task storage
- Implement WebSocket for real-time updates
- Add more AI provider support
- Implement task scheduling
- Add authentication UI
- Add monitoring/metrics
