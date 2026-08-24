# Browser Automation API

Authorized browser testing and QA automation tool with AI-powered element identification.

## Architecture

```
GitHub -> Render (Docker)
├── FastAPI Backend (Python 3.11+)
│   ├── Selenium-controlled Chromium
│   ├── AI Element Identification (Groq/OpenAI/Anthropic/Ollama)
│   ├── Task Management (in-memory + optional DB)
│   ├── Task Scheduling (cron-based)
│   ├── WebSocket Real-time Updates
│   ├── Browser Preview/Streaming
│   ├── Prometheus Metrics
│   └── Web Dashboard
└── CLI Client (Python)
```

## Project Structure

```
backend/
├── main.py                  # FastAPI application
├── config.py                # Configuration management
├── database.py              # SQLAlchemy async engine
├── api/
│   └── routes.py            # API endpoints + WebSocket
├── browser/
│   ├── driver.py            # Selenium browser control
│   └── agent.py             # Browser automation agent
├── ai/
│   ├── providers.py         # Multi-provider AI (Groq, OpenAI, Anthropic, Ollama)
│   ├── provider.py          # Provider factory
│   └── identifier.py        # Element identification
├── tasks/
│   ├── manager.py           # Task lifecycle management
│   ├── repository.py        # Database repository (optional)
│   └── scheduler.py         # Cron-based task scheduling
├── security/
│   └── auth.py              # Authentication & rate limiting
├── streaming/
│   ├── preview.py           # Browser preview streaming
│   └── websocket.py         # WebSocket connection manager
├── monitoring/
│   └── metrics.py           # Prometheus metrics
├── models/
│   ├── schemas.py           # Pydantic models
│   └── database.py          # SQLAlchemy models
└── static/
    └── index.html           # Web dashboard
client/
├── main.py                  # CLI entry point + interactive menu
├── api_client.py            # API client with all endpoints
├── ui.py                    # Terminal UI
└── config.py                # Client configuration
tests/
├── test_backend.py          # Backend unit tests
├── test_api.py              # API integration tests
└── mock_login.html          # Mock login page for testing
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
# Edit .env with your API keys

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
  -e AI_API_KEY=your_key \
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
| `AI_API_KEY` | API key for AI provider | - |
| `AI_MODEL` | AI model name | `llama-3.1-8b-instant` |
| `AI_BASE_URL` | AI provider base URL | `https://api.groq.com/openai/v1` |
| `AI_PROVIDER` | Provider type (groq/openai/anthropic/ollama) | `groq` |
| `DATABASE_URL` | Database connection string | `sqlite+aiosqlite:///./browser_automation.db` |
| `API_AUTH_TOKEN` | API authentication token | - |
| `ALLOWED_DOMAINS` | Comma-separated allowed domains | - |
| `BROWSER_SESSION_TIMEOUT` | Browser session timeout (s) | `600` |
| `TASK_TIMEOUT` | Task timeout (s) | `300` |
| `HEADLESS` | Run browser headless | `true` |
| `RATE_LIMIT_PER_MINUTE` | Rate limit per IP | `30` |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard |
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |
| POST | `/api/v1/task` | Create automation task |
| GET | `/api/v1/task/{id}` | Get task status |
| GET | `/api/v1/tasks` | List all tasks |
| GET | `/api/v1/task/{id}/events` | Get task events |
| GET | `/api/v1/task/{id}/preview` | Browser preview stream |
| POST | `/api/v1/task/{id}/manual-action` | Continue after manual action |
| POST | `/api/v1/task/{id}/stop` | Stop task |
| POST | `/api/v1/scheduled-task` | Create scheduled task |
| GET | `/api/v1/scheduled-tasks` | List scheduled tasks |
| DELETE | `/api/v1/scheduled-task/{id}` | Delete scheduled task |
| POST | `/api/v1/scheduled-task/{id}/enable` | Enable scheduled task |
| POST | `/api/v1/scheduled-task/{id}/disable` | Disable scheduled task |
| WS | `/api/v1/ws/task/{id}` | WebSocket for task updates |
| WS | `/api/v1/ws/tasks` | WebSocket for all tasks |

## Client Usage

```bash
# Interactive mode (default)
python -m client.main

# Direct commands
python -m client.main --mode run
python -m client.main --mode list
python -m client.main --mode metrics
```

The interactive client provides:
1. Run automation tasks
2. List tasks with state filtering
3. Manage scheduled tasks (CRUD)
4. View Prometheus metrics
5. Stop running tasks

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

## Monitoring

The `/metrics` endpoint exposes Prometheus-compatible metrics:

- `http_requests_total` - Total HTTP requests
- `http_request_duration_seconds` - Request latency
- `active_tasks` - Tasks by state
- `browser_sessions` - Active browser sessions
- `websocket_connections` - Active WebSocket connections

## Limitations

- Requires Chrome/Chromium installed
- AI API key required for AI element identification
- Browser preview requires direct HTTP access
- Headless mode only in production
- SQLite by default (use PostgreSQL for production)
