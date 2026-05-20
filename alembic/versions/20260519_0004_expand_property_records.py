"""expand property records

Revision ID: 20260519_0004
Revises: 20260519_0003
Create Date: 2026-05-19 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260519_0004"
down_revision = "20260519_0003"
branch_labels = None
depends_on = None


PROPERTY_RECORD_COLUMNS = [
    ("property_name", sa.String(length=255), True),
    ("unit_suite", sa.String(length=64), True),
    ("listing_id", sa.String(length=128), True),
    ("external_source_id", sa.String(length=255), True),
    ("source_dataset", sa.String(length=255), True),
    ("property_subtype", sa.String(length=64), True),
    ("asset_class", sa.String(length=64), True),
    ("usage_type", sa.String(length=64), True),
    ("zoning", sa.String(length=64), True),
    ("tenure", sa.String(length=64), True),
    ("status", sa.String(length=64), True),
    ("status_date", sa.Date(), True),
    ("listing_url", sa.Text(), True),
    ("building_area_sq_ft", sa.Integer(), True),
    ("leasable_area_sq_ft", sa.Integer(), True),
    ("lot_size_sq_ft", sa.Integer(), True),
    ("lot_size_acres", sa.Numeric(12, 4), True),
    ("floor_number", sa.Integer(), True),
    ("floor_count", sa.Integer(), True),
    ("year_built", sa.Integer(), True),
    ("year_renovated", sa.Integer(), True),
    ("ceiling_height_ft", sa.Numeric(6, 2), True),
    ("clear_height_ft", sa.Numeric(6, 2), True),
    ("dock_doors", sa.Integer(), True),
    ("drive_in_doors", sa.Integer(), True),
    ("truck_court_depth_ft", sa.Integer(), True),
    ("trailer_parking_spaces", sa.Integer(), True),
    ("parking_spaces", sa.Integer(), True),
    ("parking_ratio", sa.Numeric(8, 2), True),
    ("elevators", sa.Integer(), True),
    ("frontage_ft", sa.Integer(), True),
    ("facing", sa.String(length=64), True),
    ("furnishing_status", sa.String(length=64), True),
    ("condition_grade", sa.String(length=64), True),
    ("energy_rating", sa.String(length=64), True),
    ("green_certification", sa.String(length=128), True),
    ("accessibility_features", sa.Text(), True),
    ("asking_rent", sa.Numeric(14, 2), True),
    ("asking_rent_period", sa.String(length=32), True),
    ("rent_currency", sa.String(length=3), True),
    ("service_charge", sa.Numeric(14, 2), True),
    ("operating_expenses", sa.Numeric(14, 2), True),
    ("taxes", sa.Numeric(14, 2), True),
    ("sale_price", sa.Numeric(16, 2), True),
    ("price_currency", sa.String(length=3), True),
    ("cap_rate", sa.Numeric(6, 4), True),
    ("occupancy_pct", sa.Numeric(6, 2), True),
    ("lease_type", sa.String(length=64), True),
    ("min_lease_months", sa.Integer(), True),
    ("max_lease_months", sa.Integer(), True),
    ("incentives", sa.Text(), True),
    ("deposit_amount", sa.Numeric(14, 2), True),
    ("fit_out_allowance", sa.Numeric(14, 2), True),
    ("available_from", sa.Date(), True),
    ("vacancy_status", sa.String(length=64), True),
    ("occupancy_status", sa.String(length=64), True),
    ("country_code", sa.String(length=2), True),
    ("country", sa.String(length=128), True),
    ("region", sa.String(length=128), True),
    ("state_province", sa.String(length=128), True),
    ("county_district", sa.String(length=128), True),
    ("city", sa.String(length=128), True),
    ("locality", sa.String(length=128), True),
    ("neighborhood", sa.String(length=128), True),
    ("submarket", sa.String(length=128), True),
    ("postal_code", sa.String(length=32), True),
    ("timezone", sa.String(length=64), True),
    ("geocode_source", sa.String(length=128), True),
    ("geocode_confidence", sa.Numeric(5, 4), True),
    ("map_url", sa.Text(), True),
    ("loading_access", sa.String(length=128), True),
    ("yard_area_sq_ft", sa.Integer(), True),
    ("cold_storage", sa.Boolean(), True),
    ("sprinklered", sa.Boolean(), True),
    ("hvac_type", sa.String(length=128), True),
    ("power_capacity", sa.String(length=128), True),
    ("floor_load_psf", sa.Integer(), True),
    ("nearest_highway", sa.String(length=128), True),
    ("highway_distance_miles", sa.Numeric(8, 2), True),
    ("airport_distance_miles", sa.Numeric(8, 2), True),
    ("port_distance_miles", sa.Numeric(8, 2), True),
    ("rail_access", sa.String(length=128), True),
    ("transit_score", sa.Integer(), True),
    ("public_transit_notes", sa.Text(), True),
    ("bike_parking", sa.Boolean(), True),
    ("ev_charging", sa.Boolean(), True),
    ("fiber_available", sa.Boolean(), True),
    ("additional_information", sa.Text(), True),
]

JSONB_COLUMNS = [
    "amenities_json",
    "infrastructure_json",
    "financials_json",
    "tags_json",
    "source_metadata_json",
]


def upgrade() -> None:
    for column_name, column_type, nullable in PROPERTY_RECORD_COLUMNS:
        op.add_column("property_records", sa.Column(column_name, column_type, nullable=nullable))

    for column_name in JSONB_COLUMNS:
        op.add_column(
            "property_records",
            sa.Column(
                column_name,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )

    op.create_index(
        "ix_property_records_type_subtype_usage_status",
        "property_records",
        ["property_type", "property_subtype", "usage_type", "status"],
        unique=False,
    )
    op.create_index(
        "ix_property_records_geo_market",
        "property_records",
        ["country_code", "city", "market", "submarket", "neighborhood"],
        unique=False,
    )
    op.create_index("ix_property_records_geo_lat_lng", "property_records", ["geo_lat", "geo_lng"], unique=False)
    op.create_index("ix_property_records_available_from", "property_records", ["available_from"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_property_records_available_from", table_name="property_records")
    op.drop_index("ix_property_records_geo_lat_lng", table_name="property_records")
    op.drop_index("ix_property_records_geo_market", table_name="property_records")
    op.drop_index("ix_property_records_type_subtype_usage_status", table_name="property_records")

    for column_name in reversed(JSONB_COLUMNS):
        op.drop_column("property_records", column_name)
    for column_name, _column_type, _nullable in reversed(PROPERTY_RECORD_COLUMNS):
        op.drop_column("property_records", column_name)