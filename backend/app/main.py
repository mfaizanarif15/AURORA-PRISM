from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.auth import AuthError, authenticate_request
from app.services.observability import flush_langfuse


settings = get_settings()
configure_logging(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Starting {} environment={} api_prefix={}",
        settings.app_name,
        settings.environment,
        settings.api_v1_prefix,
    )
    yield
    logger.info("Shutting down {}", settings.app_name)
    flush_langfuse()
    logger.info("Shutdown complete")


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_origin,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_v1_prefix)


@app.middleware("http")
async def require_api_auth(request: Request, call_next):
    if _requires_auth(request):
        try:
            request.state.auth_user = authenticate_request(request, settings)
        except AuthError as exc:
            logger.warning("API authentication failed path={} reason={}", request.url.path, exc)
            return JSONResponse(
                {"detail": str(exc)},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = perf_counter()
    logger.info("HTTP request started method={} path={}", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started) * 1000
        logger.exception(
            "HTTP request failed method={} path={} duration_ms={:.2f}",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise
    duration_ms = (perf_counter() - started) * 1000
    logger.info(
        "HTTP request completed method={} path={} status_code={} duration_ms={:.2f}",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


def _requires_auth(request: Request) -> bool:
    if not settings.auth_enabled or request.method == "OPTIONS":
        return False
    path = request.url.path
    public_paths = {
        f"{settings.api_v1_prefix}/health",
        f"{settings.api_v1_prefix}/auth/login",
        f"{settings.api_v1_prefix}/auth/signup",
    }
    return path.startswith(settings.api_v1_prefix) and path not in public_paths


logger.info(
    "FastAPI app initialized title={} version={} frontend_origin={}",
    settings.app_name,
    "0.1.0",
    settings.frontend_origin,
)
