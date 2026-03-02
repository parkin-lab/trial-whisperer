from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import UserRole
from app.models.user import DomainAllowlist, User
from app.rate_limiter import limiter
from app.schemas.auth import AuthMessage, LoginRequest, RefreshRequest, RegisterRequest, TokenPair, VerifyRequest
from app.schemas.user import UserRead
from app.services.auth import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    extract_domain,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthMessage, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> AuthMessage:
    domain = extract_domain(payload.email)
    allowlist_result = await db.execute(select(DomainAllowlist).where(DomainAllowlist.domain == domain))
    allowlist_entry = allowlist_result.scalar_one_or_none()
    if allowlist_entry is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email domain is not allowed")

    user_result = await db.execute(select(User).where(User.email == payload.email.lower()))
    if user_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Email is already registered")

    user = User(
        email=payload.email.lower(),
        name=payload.name,
        hashed_password=hash_password(payload.password),
        role=UserRole.collaborator,
        active=False,
        domain=domain,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return AuthMessage(message="Registered successfully. Your account is pending owner approval.")


@router.post("/verify", response_model=AuthMessage)
async def verify_email(
    payload: VerifyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthMessage:
    try:
        subject = decode_token(payload.token, expected_type="verify")
        user_id = UUID(subject)
    except (TokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid verification token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.active = True
    await db.commit()

    return AuthMessage(message="Email verified successfully.")


@router.post("/login", response_model=TokenPair)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> TokenPair:
    _ = request
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account pending owner approval")

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(payload: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> TokenPair:
    try:
        subject = decode_token(payload.refresh_token, expected_type="refresh")
        user_id = UUID(subject)
    except (TokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserRead)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserRead:
    return UserRead.model_validate(user)
