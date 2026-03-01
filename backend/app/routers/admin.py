from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.enums import UserRole
from app.models.user import DomainAllowlist, User
from app.schemas.user import DomainAllowlistCreate, DomainAllowlistRead, UserRead, UserUpdate

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
