from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from starlette import status

from app.config import get_settings
from app.db.session import SessionFactory, ping_database
from app.indexing import check_vector_dependencies
from app.models import IngestionJob


router = APIRouter(tags=["health"])


async def _collect_job_counts() -> dict[str, dict[str, int]]:
    async with SessionFactory() as session:
        result = await session.execute(
            select(IngestionJob.job_type, IngestionJob.status, func.count())
            .group_by(IngestionJob.job_type, IngestionJob.status)
        )
        rows = list(result.all())

    counts: dict[str, dict[str, int]] = {}
    for job_type, job_status, count in rows:
        counts.setdefault(str(job_type), {})[str(job_status)] = int(count)
    return counts


@router.get("/live")
async def live() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
    }


@router.get("/ready", response_model=None)
async def ready():
    database_ready = await ping_database()
    payload = {
        "status": "ok" if database_ready else "degraded",
        "checks": {
            "database": "ok" if database_ready else "unavailable",
        },
    }

    if not database_ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)

    return payload


@router.get("/deps", response_model=None)
async def deps():
    settings = get_settings()
    database_ready = await ping_database()
    job_counts = await _collect_job_counts() if database_ready else {}
    vector_checks = await check_vector_dependencies()
    payload = {
        "status": "ok" if database_ready else "degraded",
        "checks": {
            "database": "ok" if database_ready else "unavailable",
            "qdrant": vector_checks.get("qdrant", "missing_config"),
            "embedding": vector_checks.get("embedding", "disabled"),
            "rerank": vector_checks.get("rerank", "disabled"),
            "ocr": vector_checks.get("ocr", "disabled"),
            "slack": "configured" if settings.slack_signing_secret and settings.slack_bot_token else "missing_config",
            "toolhouse": "configured" if settings.toolhouse_api_key else "missing_config",
            "toolhouse_agent": "configured" if settings.toolhouse_agent_id else "missing_config",
            "toolhouse_mcp": "configured" if settings.toolhouse_mcp_bearer_token else "missing_config",
            "background_worker": "configured" if settings.slack_bot_token and settings.slack_ingest_channels else "disabled",
        },
        "job_counts": job_counts,
    }

    if not database_ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)

    return payload
