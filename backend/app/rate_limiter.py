from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
except ModuleNotFoundError:  # pragma: no cover - fallback for offline/dev environments
    class RateLimitExceeded(Exception):
        pass

    class _NoopLimiter:
        def limit(self, _rule: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                return func

            return decorator

    async def _rate_limit_exceeded_handler(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

    limiter = _NoopLimiter()
