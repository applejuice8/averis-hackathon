import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from .api.router import api_router
from .core.config import settings
from .core.logging import configure_logging, trace_middleware
from .db.session import init_db

configure_logging(settings.log_format, settings.gcp_project_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="DockerOps API", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
app.middleware("http")(trace_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _database_health() -> dict:
    """One cheap round-trip to Neon. Never raises — an unreachable database
    is a health *report*, not a 500."""
    from .db.models import Email
    from .db.session import SessionLocal

    if SessionLocal is None:
        return {"ok": False, "detail": "NEON_DB_URI is not set"}
    try:
        async with SessionLocal() as s:
            ingested = await s.scalar(select(func.count()).select_from(Email))
        return {"ok": True, "emails_ingested": ingested}
    except Exception as e:
        # type only: the driver's message can carry the connection string
        return {"ok": False, "detail": type(e).__name__}


@app.get("/livez")
async def livez():
    """Liveness only: the process is up. Never touches the database."""
    return {"ok": True}


@app.get("/health")
async def health(response: Response):
    """What the service can actually reach right now. Deliberately does not
    call a model — reporting health should not cost quota."""
    database = await _database_health()
    data_dir = settings.resolved_data_dir
    payload = {
        "status": "ok" if database["ok"] else "degraded",
        "writes_protected": bool(settings.demo_passcode),
        "run_executor": settings.run_executor,
        "database": database,
        "llm": {
            "key_configured": bool(settings.openrouter_api_key),
            "text_models": settings.text_model_chain,
            "vision_models": settings.vision_model_chain,
            "cache_enabled": settings.enable_llm_cache,
        },
        "assists": {
            "classify": settings.enable_llm_classify,
            "field_fill": settings.enable_llm_fill,
            "vision_ocr": settings.enable_vision_ocr,
        },
        "data_dir": {"path": data_dir, "present": os.path.isdir(data_dir)},
    }
    if not database["ok"]:
        response.status_code = 503
    return payload
