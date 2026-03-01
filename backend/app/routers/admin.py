from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.audit import AuditLog
from app.models.enums import TrialStatus, UserRole
from app.models.trial import Trial
from app.models.user import DomainAllowlist, User
from app.schemas.user import AdminStatsRead, DomainAllowlistCreate, DomainAllowlistRead, UserRead, UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserRead])
async def list_users(
    _: Annotated[User, Depends(require_role(UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserRead]:
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [UserRead.model_validate(user) for user in result.scalars().all()]


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    _: Annotated[User, Depends(require_role(UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.role is not None:
        user.role = payload.role
    if payload.active is not None:
        user.active = payload.active

    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)


@router.get("/domain-allowlist", response_model=list[DomainAllowlistRead])
async def list_allowlist(
    _: Annotated[User, Depends(require_role(UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DomainAllowlistRead]:
    result = await db.execute(select(DomainAllowlist).order_by(DomainAllowlist.added_at.desc()))
    return [DomainAllowlistRead.model_validate(row) for row in result.scalars().all()]


@router.post("/domain-allowlist", response_model=DomainAllowlistRead, status_code=status.HTTP_201_CREATED)
async def add_domain(
    payload: DomainAllowlistCreate,
    owner: Annotated[User, Depends(require_role(UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DomainAllowlistRead:
    normalized = payload.domain.lower().strip()
    existing = await db.execute(select(DomainAllowlist).where(DomainAllowlist.domain == normalized))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Domain already exists")

    entry = DomainAllowlist(domain=normalized, added_by=owner.id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return DomainAllowlistRead.model_validate(entry)


@router.delete("/domain-allowlist/{allowlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    allowlist_id: UUID,
    _: Annotated[User, Depends(require_role(UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    result = await db.execute(select(DomainAllowlist).where(DomainAllowlist.id == allowlist_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")

    await db.delete(entry)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stats", response_model=AdminStatsRead)
async def get_admin_stats(
    _: Annotated[User, Depends(require_role(UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminStatsRead:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_users_result = await db.execute(select(func.count()).select_from(User))
    total_users = int(total_users_result.scalar_one() or 0)

    active_trials_result = await db.execute(
        select(func.count()).select_from(Trial).where(Trial.status == TrialStatus.active)
    )
    active_trials = int(active_trials_result.scalar_one() or 0)

    total_screens_result = await db.execute(select(func.count()).select_from(AuditLog))
    total_screens = int(total_screens_result.scalar_one() or 0)

    screens_this_month_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.timestamp >= month_start)
    )
    screens_this_month = int(screens_this_month_result.scalar_one() or 0)

    users_by_role_result = await db.execute(select(User.role, func.count(User.id)).group_by(User.role))
    users_by_role = {str(role): int(count) for role, count in users_by_role_result.all()}

    trials_by_status_result = await db.execute(select(Trial.status, func.count(Trial.id)).group_by(Trial.status))
    trials_by_status = {str(status): int(count) for status, count in trials_by_status_result.all()}

    return AdminStatsRead(
        total_users=total_users,
        active_trials=active_trials,
        total_screens=total_screens,
        screens_this_month=screens_this_month,
        users_by_role=users_by_role,
        trials_by_status=trials_by_status,
    )
