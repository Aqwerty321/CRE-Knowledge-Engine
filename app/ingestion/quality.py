from __future__ import annotations

from app.db.session import SessionFactory
from app.retrieval.structured_service import collect_data_quality_report


async def collect_ingestion_quality_report() -> dict[str, object]:
    async with SessionFactory() as session:
        return await collect_data_quality_report(session)


__all__ = ["collect_ingestion_quality_report"]
