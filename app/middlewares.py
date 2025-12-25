from datetime import timedelta, datetime
from typing import Any

from aws_lambda_powertools import Logger
from fastapi import status
from fastapi.requests import Request
from fastapi.responses import Response, UJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app import settings

clients: dict[str, Any] = {}
logger = Logger()


class RateLimitingMiddleware(BaseHTTPMiddleware):
    RATE_LIMIT_DURATION = timedelta(seconds=settings.rate_limit_duration_in_seconds)

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if settings.rate_limiting:
            client_ip = request.client.host if request.client else None
            if client_ip:
                rate_limited_response = self._check_rate_limit(client_ip)
                if rate_limited_response:
                    return rate_limited_response
                response = await call_next(request)
                response.headers.update(self._get_rate_limit_headers(clients[client_ip]))
                return response
            else:
                logger.warning("Missing client information. Skipping rate limiting")
        else:
            logger.info("Rate limiting is turned off")
        return await call_next(request)

    def _check_rate_limit(self, client_ip: str) -> UJSONResponse | None:
        client = clients.get(client_ip, {"request_count": 0, "last_request": datetime.min})
        if (datetime.now() - client["last_request"]) > self.RATE_LIMIT_DURATION:
            client["request_count"] = 1
        else:
            if client["request_count"] >= settings.rate_limit_requests:
                logger.warning(
                    "The client has exceeded the rate limit and has been rate limited",
                    host=client_ip,
                )
                return UJSONResponse(
                    content={"message": "Rate limit exceeded. Please try again later"},
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers=self._get_rate_limit_headers(client),
                )
            client["request_count"] += 1
        client["last_request"] = datetime.now()
        clients[client_ip] = client
        return None

    def _get_rate_limit_headers(self, client: dict[str, Any]) -> dict[str, Any]:
        return {
            "X-RateLimit-Limit": str(settings.rate_limit_requests),
            "X-RateLimit-Remaining": str(settings.rate_limit_requests - client["request_count"]),
            "X-RateLimit-Reset": str(
                int((client["last_request"].replace(second=0, microsecond=0) + timedelta(minutes=1)).timestamp())
            ),
        }
