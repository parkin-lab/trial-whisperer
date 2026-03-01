# Trial Whisperer

Clinical trial eligibility screening portal for research teams.

## Features
- Multi-user portal with role-based access (Owner, PI, Coordinator, Collaborator)
- Protocol ingestion (PDF/DOCX) with ClinicalTrials.gov auto-matching
- Deterministic eligibility engine — zero LLM hallucination risk on pass/fail decisions
- LLM-assisted criteria parsing at ingestion time (human review required before activation)
- Dynamic patient screener across all active trials (6 indications: AML, ALL, Lymphoma, MM, Transplant, GVHD)
- Near-miss detection: shows exactly how close a patient was to meeting each criterion
- Protocol Q&A with RAG (source-cited answers from protocol text)
- Full audit trail (no PHI stored — pass/fail only)
- Domain allowlist authentication

## Zero PHI Design
Patient data entered in the screener is never written to the server. All evaluation happens in-memory. The audit log records only pass/fail outcomes per criterion — never patient values.

## Quick Start

### Prerequisites
- Docker + Docker Compose
- OpenAI API key (optional — LLM features disabled without it)

### Setup
1. Clone repo
2. Copy `.env.example` → `.env` and fill in values
3. Set `INITIAL_OWNER_EMAIL`, `INITIAL_OWNER_PASSWORD`, `INITIAL_OWNER_DOMAIN`
4. Run: `docker compose up -d`
5. Navigate to http://localhost:3000

### First Login
The owner account is created automatically on first startup using `INITIAL_OWNER_EMAIL` / `INITIAL_OWNER_PASSWORD`. Log in and add additional users via the Admin panel.

## Development

### Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

### Frontend
cd frontend
npm install
npm run dev

### Tests
cd backend && pytest

## Architecture
- Backend: FastAPI (Python 3.11+)
- Frontend: React + Tailwind (Vite)
- Database: PostgreSQL + pgvector
- Background jobs: Redis + ARQ
- Auth: JWT + domain allowlist + email verification

## Roles
| Role | Can Do |
|---|---|
| Owner | Everything + user management + audit purge |
| PI | Ingest protocols, approve criteria, archive trials |
| Coordinator | Same as PI + run screener |
| Collaborator | Run screener + protocol Q&A (read-only) |
