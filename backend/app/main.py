import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.middleware.logging import JsonLoggingMiddleware
from app.models.enums import UserRole
from app.models.user import DomainAllowlist, User
from app.rate_limiter import RateLimitExceeded, _rate_limit_exceeded_handler, limiter
from app.routers import admin, audit, auth, awareness, criteria, ctg, qa, screener, trials
from app.services.auth import extract_domain, hash_password

settings = get_settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _create_initial_owner_if_needed() -> None:
    if not settings.initial_owner_email:
        return

    if not settings.initial_owner_password:
        logger.warning("INITIAL_OWNER_EMAIL is set but INITIAL_OWNER_PASSWORD is missing; skipping owner bootstrap")
        return

    owner_email = settings.initial_owner_email.lower().strip()
    owner_domain = extract_domain(owner_email)
    configured_domain = (settings.initial_owner_domain or owner_domain).lower().strip()

    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(User)
            .values(
                email=owner_email,
                name="Initial Owner",
                hashed_password=hash_password(settings.initial_owner_password),
                role=UserRole.owner,
                active=True,
                domain=owner_domain,
            )
            .on_conflict_do_nothing(index_elements=["email"])
            .returning(User.id)
        )
        result = await session.execute(stmt)
        owner_id = result.scalar_one_or_none()
        if owner_id is None:
            return

        for domain in {configured_domain, owner_domain}:
            if domain:
                allowlist_stmt = (
                    pg_insert(DomainAllowlist)
                    .values(domain=domain, added_by=owner_id)
                    .on_conflict_do_nothing(index_elements=["domain"])
                )
                await session.execute(allowlist_stmt)

        await session.commit()
        logger.info("Created initial owner account", extra={"email": owner_email, "domain": configured_domain})


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    # Only enforce in production (Railway sets RAILWAY_ENVIRONMENT)
    if settings.secret_key in {"change-me", "changeme", "secret", ""} and os.getenv("RAILWAY_ENVIRONMENT"):
        raise RuntimeError("SECRET_KEY must be set to a secure random value before starting the application.")
    await _create_initial_owner_if_needed()
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
app.include_router(awareness.router)
app.include_router(criteria.router)
app.include_router(ctg.router)
app.include_router(screener.router)
app.include_router(qa.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}
