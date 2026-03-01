# Trial Whisperer

Clinical trial eligibility screening portal.

## Stack
- Backend: FastAPI + SQLAlchemy async + Alembic
- Frontend: React + Tailwind + Vite
- Database: PostgreSQL + pgvector
- Queue: Redis + ARQ

## Quick start
1. Copy env file:
```bash
cp .env.example .env
```
2. Start services:
```bash
docker compose up --build
```
3. Run migrations:
```bash
docker compose exec backend alembic upgrade head
```
4. Open:
- API docs: http://localhost:8000/docs
- Frontend: http://localhost:5173
- pgAdmin: http://localhost:5050

## Backend local dev
```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Frontend local dev
```bash
cd frontend
npm install
npm run dev
```

## Tests
```bash
cd backend
pytest -q
```

## Notes
- No patient PHI should be ingested.
- File uploads are stored in `./uploads/`.
