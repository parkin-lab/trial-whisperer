import json
import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("trial_whisperer.request")


class JsonLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        start = time.perf_counter()

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            payload = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": status_code if "status_code" in locals() else 500,
                "duration_ms": duration_ms,
            }
            logger.info(json.dumps(payload))
