"""add optional postgis geo point

Revision ID: 20260519_0005
Revises: 20260519_0004
Create Date: 2026-05-19 00:00:00

"""
from __future__ import annotations

from alembic import op


revision = "20260519_0005"
down_revision = "20260519_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS postgis;
        EXCEPTION
            WHEN OTHERS THEN
                RAISE NOTICE 'PostGIS extension is not available for this database role/image; skipping geo_point setup. Error: %', SQLERRM;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
                ALTER TABLE property_records ADD COLUMN IF NOT EXISTS geo_point geography(Point, 4326);

                UPDATE property_records
                SET geo_point = ST_SetSRID(ST_MakePoint(geo_lng::double precision, geo_lat::double precision), 4326)::geography
                WHERE geo_lat IS NOT NULL
                  AND geo_lng IS NOT NULL
                  AND geo_point IS NULL;

                CREATE OR REPLACE FUNCTION set_property_record_geo_point()
                RETURNS trigger AS $trigger$
                BEGIN
                    IF NEW.geo_lat IS NULL OR NEW.geo_lng IS NULL THEN
                        NEW.geo_point := NULL;
                    ELSE
                        NEW.geo_point := ST_SetSRID(ST_MakePoint(NEW.geo_lng::double precision, NEW.geo_lat::double precision), 4326)::geography;
                    END IF;
                    RETURN NEW;
                END;
                $trigger$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS trg_property_records_geo_point ON property_records;
                CREATE TRIGGER trg_property_records_geo_point
                BEFORE INSERT OR UPDATE OF geo_lat, geo_lng ON property_records
                FOR EACH ROW
                EXECUTE FUNCTION set_property_record_geo_point();

                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_property_records_geo_point_gist ON property_records USING GIST (geo_point)';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'property_records' AND column_name = 'geo_point') THEN
                DROP TRIGGER IF EXISTS trg_property_records_geo_point ON property_records;
                DROP FUNCTION IF EXISTS set_property_record_geo_point();
                DROP INDEX IF EXISTS ix_property_records_geo_point_gist;
                ALTER TABLE property_records DROP COLUMN IF EXISTS geo_point;
            END IF;
        END
        $$;
        """
    )