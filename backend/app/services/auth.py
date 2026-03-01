from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


class TokenError(ValueError):
    pass


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(user_id: UUID) -> str:
    return _create_token(str(user_id), "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(user_id: UUID) -> str:
    return _create_token(str(user_id), "refresh", timedelta(days=settings.refresh_token_expire_days))


def create_verification_token(user_id: UUID) -> str:
    return _create_token(str(user_id), "verify", timedelta(hours=settings.verify_token_expire_hours))


def decode_token(token: str, expected_type: str) -> str:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise TokenError("Invalid token") from exc

    token_type = payload.get("type")
    subject = payload.get("sub")
    if token_type != expected_type or not subject:
        raise TokenError("Invalid token type")
    return str(subject)


def extract_domain(email: str) -> str:
    return email.split("@")[-1].lower().strip()
