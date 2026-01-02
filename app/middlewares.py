from datetime import timedelta, datetime
from typing import Any
import time

from aws_lambda_powertools import Logger
from fastapi import status
from fastapi.requests import Request
from fastapi.responses import Response, UJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app import settings

clients: dict[str, Any] = {}
logger = Logger()


class RateLimitingMiddleware(BaseHTTPMiddleware):
    @property
    def _window(self) -> timedelta:
        return timedelta(seconds=settings.rate_limit_duration_in_seconds)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not settings.rate_limiting:
            return await call_next(request)

        client_ip = request.client.host if request.client else None
        if not client_ip:
            return await call_next(request)

        limited = self._check_rate_limit(client_ip)
        if limited is not None:
            return limited

        response = await call_next(request)
        response.headers.update(self._rate_limit_headers(clients[client_ip]))
        return response

    def _check_rate_limit(self, client_ip: str) -> Response | None:
        now = datetime.now()

        client = clients.setdefault(
            client_ip,
            {"request_count": 0, "last_request": now},
        )

        if now - client["last_request"] > self._window:
            client["request_count"] = 1
        else:
            if client["request_count"] >= settings.rate_limit_requests:
                logger.warning("Rate limit exceeded", host=client_ip)
                return UJSONResponse(
                    {"message": "Rate limit exceeded. Please try again later"},
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers=self._rate_limit_headers(client),
                )
            client["request_count"] += 1

        client["last_request"] = now
        return None

    def _rate_limit_headers(self, client: dict[str, Any]) -> dict[str, str]:
        remaining = max(
            settings.rate_limit_requests - client["request_count"],
            0,
        )

        reset = int((client["last_request"] + self._window).timestamp())

        return {
            "X-RateLimit-Limit": str(settings.rate_limit_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset),
        }


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.debug:
            return await call_next(request)

        start = time.perf_counter()

        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path
        query_params = dict(request.query_params)
        headers = dict(request.headers)

        body = None
        if method in {"POST", "PUT", "PATCH"}:
            try:
                raw = await request.body()
                body = raw.decode(errors="replace") if raw else None
            except Exception:
                logger.debug("Failed to read request body")

        logger.debug(
            "Incoming request",
            method=method,
            path=path,
            client_ip=client_ip,
            query_params=query_params,
            headers=headers,
            body=body,
        )

        response = await call_next(request)

        process_time = time.perf_counter() - start
        response.headers["X-Process-Time"] = f"{process_time:.6f}"

        logger.debug(
            "Outgoing response",
            method=method,
            path=path,
            client_ip=client_ip,
            status_code=response.status_code,
            process_time=process_time,
        )

        return response
