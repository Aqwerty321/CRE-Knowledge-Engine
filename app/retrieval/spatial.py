from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_postgis_status(session: AsyncSession) -> dict[str, Any]:
    try:
        result = await session.execute(
            text(
                """
                SELECT
                    EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') AS extension_enabled,
                    EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'property_records'
                          AND column_name = 'geo_point'
                    ) AS geo_point_column,
                    EXISTS (
                        SELECT 1
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'ix_property_records_geo_point_gist'
                    ) AS gist_index
                """
            )
        )
        row = result.mappings().first() or {}
    except Exception as exc:  # noqa: BLE001 - status reporting must not break retrieval paths
        return {
            "status": "unavailable",
            "extension_enabled": False,
            "geo_point_column": False,
            "gist_index": False,
            "error": str(exc),
        }

    extension_enabled = bool(row.get("extension_enabled"))
    geo_point_column = bool(row.get("geo_point_column"))
    gist_index = bool(row.get("gist_index"))
    return {
        "status": "ready" if extension_enabled and geo_point_column and gist_index else "numeric_fallback",
        "extension_enabled": extension_enabled,
        "geo_point_column": geo_point_column,
        "gist_index": gist_index,
    }