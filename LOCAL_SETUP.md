# Local Setup

## Prerequisites
- Docker + Docker Compose

## Quick Start

1. Clone the repo
2. Copy and configure env:
   cp .env.example .env
   # Edit .env: set SECRET_KEY, INITIAL_OWNER_EMAIL/PASSWORD/DOMAIN
   # Add OPENCLAW_GATEWAY_TOKEN (see LLM Setup below)

3. Start everything:
   docker compose up -d

4. Run database migrations (first time only):
   docker compose exec backend alembic upgrade head

5. Open http://localhost:3000

## First Login
Use the INITIAL_OWNER_EMAIL and INITIAL_OWNER_PASSWORD you set in .env.

## Services
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs
- pgAdmin (dev): http://localhost:5050 (admin@example.com / admin)
  Start with: docker compose --profile dev up -d

## LLM Setup
Trial Whisperer uses Claude via your local OpenClaw gateway - no separate API keys needed.

1. Get your OpenClaw gateway token:
   cat ~/.openclaw/openclaw.json | python3 -c "import json,sys; c=json.load(sys.stdin); print(c['gateway']['auth']['token'])"

2. Add to your .env:
   OPENCLAW_GATEWAY_TOKEN=<token from above>
   OPENCLAW_GATEWAY_URL=http://host.docker.internal:18789

## External Access (optional)
To expose via public HTTPS URL using Cloudflare Tunnel:
1. Install cloudflared: brew install cloudflare/cloudflare/cloudflared
2. cloudflared tunnel login
3. cloudflared tunnel create trial-whisperer
4. cloudflared tunnel route dns trial-whisperer trial.yourdomain.com
5. cloudflared tunnel run --url http://localhost:3000 trial-whisperer
