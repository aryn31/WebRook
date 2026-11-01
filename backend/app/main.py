from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import install_error_handlers
from app.logconfig import configure_logging
from app.metrics import router as metrics_router
from app.metrics import track_requests
from app.routers import api_keys, audit_logs, auth, deliveries, endpoints, events, health, stats, usage

configure_logging()

app = FastAPI(
    title="HookFlow API",
    version="1.0.0",
    description="Send events once; HookFlow delivers, retries and records them. See docs/api.md.",
)
install_error_handlers(app)
app.middleware("http")(track_requests)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Reject oversized requests early, before reading the body."""
    max_bytes = get_settings().max_payload_bytes
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > max_bytes:
        return JSONResponse(
            {"error": {"code": "payload_too_large", "message": f"Request body exceeds the {max_bytes} byte limit.",
                       "details": None}},
            status_code=413,
        )
    return await call_next(request)


for r in (health, auth, api_keys, endpoints, events, deliveries, stats, usage, audit_logs):
    app.include_router(r.router)
app.include_router(metrics_router)
