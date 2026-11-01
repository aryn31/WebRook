from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import ops
from app.config import get_settings
from app.db import engine
from app.ratelimit import get_redis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    ok = all(v == "ok" for v in checks.values())
    # Reported, but doesn't fail the check: restarting the API wouldn't fix a stopped worker.
    silence = ops.worker_silence_seconds()
    if silence is None:
        worker = "unknown"
    else:
        worker = "ok" if silence <= get_settings().alert_worker_silence_seconds else "stale"
    return JSONResponse({"status": "ok" if ok else "unavailable", "checks": checks, "worker": worker},
                        status_code=200 if ok else 503)
