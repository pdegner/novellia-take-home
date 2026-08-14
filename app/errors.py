"""One error shape for every failure.

FastAPI's defaults return three different bodies for 404s, validation failures,
and crashes. A client should not have to branch on which. Everything here
normalises to `{"error": {"code": ..., "message": ...}}`.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import DomainError

logger = logging.getLogger(__name__)

_STATUS_CODES = {
    404: "NOT_FOUND",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
}


def _envelope(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Routes may raise HTTPException with either a plain string or our
        # {"code": ..., "message": ...} dict; support both.
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return _envelope(exc.status_code, exc.detail["code"], exc.detail.get("message", ""))
        default = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        return _envelope(exc.status_code, default, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in exc.errors()
        )
        return _envelope(422, "VALIDATION_ERROR", problems or "Invalid request")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return a generic message. Stack traces and internal
        # identifiers do not belong in a response body on a health API.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _envelope(500, "INTERNAL_ERROR", "An unexpected error occurred")
