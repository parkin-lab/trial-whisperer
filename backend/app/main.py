import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.middleware.logging import JsonLoggingMiddleware
from app.models.enums import UserRole
from app.models.user import DomainAllowlist, User
from app.routers import admin, audit, auth, criteria, ctg, qa, screener, trials
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
        existing_user_count = int(await session.scalar(select(func.count()).select_from(User)) or 0)
        if existing_user_count > 0:
            return

        owner = User(
            email=owner_email,
            name="Initial Owner",
            hashed_password=hash_password(settings.initial_owner_password),
            role=UserRole.owner,
            active=True,
            domain=owner_domain,
        )
        session.add(owner)
        await session.flush()

        for domain in {configured_domain, owner_domain}:
            if domain:
                session.add(DomainAllowlist(domain=domain, added_by=owner.id))

        await session.commit()
        logger.info("Created initial owner account", extra={"email": owner_email, "domain": configured_domain})


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    await _create_initial_owner_if_needed()
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

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
app.include_router(qa.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}
