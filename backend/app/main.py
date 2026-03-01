import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.logging import JsonLoggingMiddleware
from app.routers import admin, audit, auth, criteria, ctg, screener, trials

settings = get_settings()
logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(JsonLoggingMiddleware)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(audit.router)
app.include_router(trials.router)
app.include_router(criteria.router)
app.include_router(ctg.router)
app.include_router(screener.router)


@app.on_event("startup")
async def startup() -> None:
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
