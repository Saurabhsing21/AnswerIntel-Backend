from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Domain error rendered as {"error": {"code", "message"}} (PRD section 85)."""

    def __init__(self, status_code: int, code: str, message: str, limit: str | None = None, details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.limit = limit  # which plan limit was hit, so the UI can offer an upgrade
        self.details = details  # structured facts the UI renders itself, e.g. which projects hold the question pool


def ai_unavailable() -> AppError:
    """What users see whenever the AI service is not configured or a call to it failed."""
    return AppError(503, "AI_UNAVAILABLE", "We couldn't reach the AI service. Try again in a minute.")


def _body(code: str, message: str, limit: str | None = None, details: dict | None = None) -> dict:
    # "detail" kept for backwards compatibility with existing clients and tests.
    error = {"code": code, "message": message}
    if limit:
        error["limit"] = limit
    if details:
        error["details"] = details
    return {"error": error, "detail": message}


_HTTP_CODES = {
    400: "INVALID_REQUEST",
    401: "AUTH_UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.limit, exc.details))

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        code = _HTTP_CODES.get(exc.status_code, "ERROR")
        return JSONResponse(status_code=exc.status_code, content=_body(code, message))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        message = f"{field}: {first.get('msg', 'Invalid value')}" if field else "Invalid request."
        return JSONResponse(status_code=422, content=_body("VALIDATION_ERROR", message))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, __: Exception):
        # Never leak stack traces, SQL or provider details.
        return JSONResponse(status_code=500, content=_body("INTERNAL_ERROR", "Something went wrong."))
