from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


DEFAULT_ROW_COUNT = 2400
DEFAULT_SEED = 20260519


@dataclass(frozen=True)
class MarketSeed:
    market: str
    city: str
    region: str
    state_province: str
    country: str
    country_code: str
    timezone: str
    lat: float
    lng: float
    neighborhoods: tuple[str, ...]
    highways: tuple[str, ...]
    airport_distance_miles: float
    port_distance_miles: float


US_MARKETS = (
    MarketSeed("New York", "New York", "Northeast", "NY", "United States", "US", "America/New_York", 40.7128, -74.0060, ("SoHo", "Brooklyn", "Queens", "Hudson Yards"), ("I-95", "I-278", "I-495"), 15.0, 8.0),
    MarketSeed("Boston", "Boston", "Northeast", "MA", "United States", "US", "America/New_York", 42.3601, -71.0589, ("Seaport", "Back Bay", "Cambridge", "Somerville"), ("I-90", "I-93", "Route 1"), 5.0, 4.0),
    MarketSeed("Washington DC", "Washington", "Mid-Atlantic", "DC", "United States", "US", "America/New_York", 38.9072, -77.0369, ("NoMa", "Capitol Riverfront", "Georgetown", "Union Market"), ("I-395", "I-66", "I-495"), 6.0, 35.0),
    MarketSeed("Atlanta", "Atlanta", "Southeast", "GA", "United States", "US", "America/New_York", 33.7490, -84.3880, ("Midtown", "Buckhead", "Airport South", "Westside"), ("I-75", "I-85", "I-285"), 9.0, 250.0),
    MarketSeed("Miami", "Miami", "Southeast", "FL", "United States", "US", "America/New_York", 25.7617, -80.1918, ("Brickell", "Wynwood", "Doral", "Medley"), ("I-95", "SR 826", "Florida Turnpike"), 8.0, 3.0),
    MarketSeed("Chicago", "Chicago", "Midwest", "IL", "United States", "US", "America/Chicago", 41.8781, -87.6298, ("Fulton Market", "River North", "O'Hare", "South Loop"), ("I-90", "I-94", "I-290"), 16.0, 780.0),
    MarketSeed("Dallas-Fort Worth", "Dallas", "South Central", "TX", "United States", "US", "America/Chicago", 32.7767, -96.7970, ("Uptown", "Design District", "Las Colinas", "Alliance"), ("I-35E", "I-30", "I-635"), 20.0, 260.0),
    MarketSeed("Houston", "Houston", "South Central", "TX", "United States", "US", "America/Chicago", 29.7604, -95.3698, ("Energy Corridor", "Downtown", "Katy", "Port Houston"), ("I-10", "I-45", "I-610"), 22.0, 9.0),
    MarketSeed("Austin", "Austin", "South Central", "TX", "United States", "US", "America/Chicago", 30.2672, -97.7431, ("Domain", "East Austin", "South Congress", "Round Rock"), ("I-35", "US 183", "SH 130"), 11.0, 210.0),
    MarketSeed("Denver", "Denver", "Mountain", "CO", "United States", "US", "America/Denver", 39.7392, -104.9903, ("RiNo", "LoDo", "Aurora", "Central Park"), ("I-25", "I-70", "E-470"), 24.0, 1000.0),
    MarketSeed("Los Angeles/Inland Empire", "Los Angeles", "West", "CA", "United States", "US", "America/Los_Angeles", 34.0522, -118.2437, ("Arts District", "South Bay", "Vernon", "Inland Empire"), ("I-5", "I-10", "SR 60"), 18.0, 24.0),
    MarketSeed("San Francisco Bay Area", "San Francisco", "West", "CA", "United States", "US", "America/Los_Angeles", 37.7749, -122.4194, ("SoMa", "Mission Bay", "Oakland", "San Mateo"), ("US 101", "I-80", "I-880"), 14.0, 7.0),
    MarketSeed("Seattle", "Seattle", "Pacific Northwest", "WA", "United States", "US", "America/Los_Angeles", 47.6062, -122.3321, ("South Lake Union", "Pioneer Square", "Kent Valley", "Bellevue"), ("I-5", "I-90", "SR 167"), 14.0, 5.0),
)

EUROPE_MARKETS = (
    MarketSeed("London", "London", "Western Europe", "England", "United Kingdom", "GB", "Europe/London", 51.5072, -0.1276, ("Shoreditch", "City Fringe", "Park Royal", "Canary Wharf"), ("M25", "M4", "A13"), 18.0, 23.0),
    MarketSeed("Manchester", "Manchester", "Western Europe", "England", "United Kingdom", "GB", "Europe/London", 53.4808, -2.2426, ("Northern Quarter", "Salford", "Trafford Park", "Ancoats"), ("M60", "M62", "M56"), 9.0, 35.0),
    MarketSeed("Dublin", "Dublin", "Western Europe", "Leinster", "Ireland", "IE", "Europe/Dublin", 53.3498, -6.2603, ("Docklands", "Sandyford", "Ballymount", "Citywest"), ("M50", "N7", "M1"), 7.0, 4.0),
    MarketSeed("Paris", "Paris", "Western Europe", "Ile-de-France", "France", "FR", "Europe/Paris", 48.8566, 2.3522, ("La Defense", "Le Marais", "Saint-Denis", "Rungis"), ("A1", "A6", "A86"), 17.0, 100.0),
    MarketSeed("Lyon", "Lyon", "Western Europe", "Auvergne-Rhone-Alpes", "France", "FR", "Europe/Paris", 45.7640, 4.8357, ("Part-Dieu", "Confluence", "Venissieux", "Saint-Priest"), ("A6", "A7", "A43"), 15.0, 200.0),
    MarketSeed("Berlin", "Berlin", "Central Europe", "Berlin", "Germany", "DE", "Europe/Berlin", 52.5200, 13.4050, ("Mitte", "Kreuzberg", "Adlershof", "Tempelhof"), ("A100", "A10", "A113"), 16.0, 155.0),
    MarketSeed("Hamburg", "Hamburg", "Central Europe", "Hamburg", "Germany", "DE", "Europe/Berlin", 53.5511, 9.9937, ("HafenCity", "Altona", "Billbrook", "Harburg"), ("A1", "A7", "A24"), 8.0, 3.0),
    MarketSeed("Munich", "Munich", "Central Europe", "Bavaria", "Germany", "DE", "Europe/Berlin", 48.1351, 11.5820, ("Maxvorstadt", "Schwabing", "Garching", "Freiham"), ("A8", "A9", "A99"), 22.0, 300.0),
    MarketSeed("Amsterdam/Rotterdam", "Amsterdam", "Western Europe", "North Holland", "Netherlands", "NL", "Europe/Amsterdam", 52.3676, 4.9041, ("Zuidas", "Sloterdijk", "Schiphol", "Rotterdam Port"), ("A4", "A10", "A12"), 9.0, 46.0),
    MarketSeed("Madrid", "Madrid", "Southern Europe", "Community of Madrid", "Spain", "ES", "Europe/Madrid", 40.4168, -3.7038, ("Salamanca", "Chamartin", "Getafe", "Coslada"), ("M-30", "M-40", "A-2"), 10.0, 220.0),
    MarketSeed("Barcelona", "Barcelona", "Southern Europe", "Catalonia", "Spain", "ES", "Europe/Madrid", 41.3874, 2.1686, ("22@", "Eixample", "Zona Franca", "Sant Cugat"), ("B-10", "AP-7", "C-32"), 9.0, 5.0),
    MarketSeed("Milan", "Milan", "Southern Europe", "Lombardy", "Italy", "IT", "Europe/Rome", 45.4642, 9.1900, ("Porta Nuova", "Zona Tortona", "Sesto", "Linate"), ("A4", "A7", "A51"), 8.0, 90.0),
    MarketSeed("Stockholm", "Stockholm", "Northern Europe", "Stockholm County", "Sweden", "SE", "Europe/Stockholm", 59.3293, 18.0686, ("Norrmalm", "Sodermalm", "Kista", "Arlanda"), ("E4", "E18", "Route 73"), 25.0, 36.0),
    MarketSeed("Copenhagen", "Copenhagen", "Northern Europe", "Capital Region", "Denmark", "DK", "Europe/Copenhagen", 55.6761, 12.5683, ("Indre By", "Nordhavn", "Orestad", "Glostrup"), ("E20", "E47", "Ring 3"), 8.0, 4.0),
)

GLOBAL_CONTROL_MARKETS = (
    MarketSeed("Toronto", "Toronto", "North America", "ON", "Canada", "CA", "America/Toronto", 43.6532, -79.3832, ("Financial District", "Liberty Village", "Mississauga", "Vaughan"), ("401", "Gardiner", "QEW"), 18.0, 2.0),
    MarketSeed("Singapore", "Singapore", "Asia Pacific", "Central Region", "Singapore", "SG", "Asia/Singapore", 1.3521, 103.8198, ("CBD", "Jurong", "Changi", "Tuas"), ("PIE", "ECP", "AYE"), 11.0, 8.0),
)

PROPERTY_TYPE_SEQUENCE = (
    ["industrial"] * 22
    + ["office"] * 18
    + ["retail"] * 14
    + ["multifamily"] * 12
    + ["mixed_use"] * 10
    + ["land"] * 8
    + ["hospitality"] * 5
    + ["medical"] * 4
    + ["data_center"] * 3
    + ["self_storage"] * 2
    + ["parking"] * 2
)

STATUS_SEQUENCE = (
    ["available"] * 35
    + ["coming_soon"] * 18
    + ["under_offer"] * 12
    + ["leased"] * 12
    + ["sold"] * 7
    + ["withdrawn"] * 5
    + ["pipeline"] * 6
    + ["unknown"] * 5
)

FACING_SEQUENCE = ("north", "south", "east", "west", "corner", "dual_aspect", "courtyard", "street_front")
COASTAL_FACING_SEQUENCE = ("waterfront", "sea_facing", "waterfront", "harbor_view", "waterfront", "bay_front")
COASTAL_FACING_NEIGHBORHOODS = {
    "Brickell",
    "Seaport",
    "South Bay",
    "Mission Bay",
    "South Lake Union",
    "Pioneer Square",
    "Canary Wharf",
    "Docklands",
    "HafenCity",
    "Rotterdam Port",
    "22@",
    "Nordhavn",
    "Financial District",
    "CBD",
    "Changi",
    "Tuas",
}
COASTAL_FACING_NOTES = {
    "waterfront": "Waterfront-oriented frontage is part of this deterministic coastal demo profile.",
    "sea_facing": "Sea-facing frontage is part of this deterministic coastal demo profile.",
    "harbor_view": "Harbor-view frontage is part of this deterministic coastal demo profile.",
    "bay_front": "Bay-front exposure is part of this deterministic coastal demo profile.",
}
FURNISHING_SEQUENCE = ("unfurnished", "warm_shell", "shell", "partially_furnished", "furnished", "turnkey")
STREET_NAMES = ("Market", "Harbor", "Canal", "Foundry", "Union", "Beacon", "Spruce", "River", "Orchard", "Gallery", "Skyline", "Logistics")
STREET_SUFFIXES = ("St", "Ave", "Rd", "Ln", "Pkwy", "Way", "Loop", "Row")

CSV_FIELDNAMES = [
    "listing_id",
    "property_name",
    "address",
    "property_type",
    "property_subtype",
    "usage_type",
    "status",
    "sq_ft",
    "price_per_sq_ft",
    "price_basis",
    "sale_price",
    "cap_rate",
    "availability",
    "availability_date",
    "market",
    "country_code",
    "country",
    "state_province",
    "city",
    "locality",
    "neighborhood",
    "submarket",
    "postal_code",
    "geo_lat",
    "geo_lng",
    "map_url",
    "facing",
    "furnishing_status",
    "loading_access",
    "dock_doors",
    "drive_in_doors",
    "parking_spaces",
    "nearest_highway",
    "rail_access",
    "additional_information",
]


def _weighted_markets(row_count: int) -> list[MarketSeed]:
    us_count = round(row_count * 0.60)
    europe_count = round(row_count * 0.35)
    global_count = row_count - us_count - europe_count
    markets: list[MarketSeed] = []
    for index in range(us_count):
        markets.append(US_MARKETS[index % len(US_MARKETS)])
    for index in range(europe_count):
        markets.append(EUROPE_MARKETS[index % len(EUROPE_MARKETS)])
    for index in range(global_count):
        markets.append(GLOBAL_CONTROL_MARKETS[index % len(GLOBAL_CONTROL_MARKETS)])
    return markets


def _property_type_profile(property_type: str, rng: random.Random) -> dict[str, Any]:
    if property_type in {"industrial", "cold_storage"}:
        sq_ft = rng.randint(22000, 225000)
        price = rng.randint(36, 58)
        return {
            "property_subtype": rng.choice(["last_mile", "distribution", "flex", "warehouse", "cold_storage"]),
            "usage_type": "logistics",
            "sq_ft": sq_ft,
            "price_per_sq_ft": f"{price}.00",
            "dock_doors": rng.randint(2, 42),
            "drive_in_doors": rng.randint(0, 6),
            "clear_height_ft": f"{rng.choice([24, 28, 32, 36, 40])}.00",
            "loading_access": rng.choice(["dock_high", "grade_level", "cross_dock", "shared_yard"]),
            "yard_area_sq_ft": rng.randint(5000, 90000),
            "truck_court_depth_ft": rng.choice([110, 120, 130, 140, 150, 185]),
            "trailer_parking_spaces": rng.randint(4, 160),
        }
    if property_type == "office":
        sq_ft = rng.randint(3500, 90000)
        price = rng.randint(52, 88)
        return {
            "property_subtype": rng.choice(["creative", "class_a", "class_b", "medical_office", "coworking_ready"]),
            "usage_type": "office",
            "sq_ft": sq_ft,
            "price_per_sq_ft": f"{price}.00",
            "floor_number": rng.randint(1, 35),
            "floor_count": rng.randint(4, 48),
            "elevators": rng.randint(2, 14),
            "parking_ratio": f"{rng.choice([1.5, 2.0, 2.5, 3.0])}",
        }
    if property_type == "retail":
        sq_ft = rng.randint(1200, 38000)
        price = rng.randint(38, 96)
        return {
            "property_subtype": rng.choice(["storefront", "restaurant_ready", "showroom", "high_street", "neighborhood_center"]),
            "usage_type": "retail",
            "sq_ft": sq_ft,
            "price_per_sq_ft": f"{price}.00",
            "frontage_ft": rng.randint(20, 240),
        }
    if property_type == "multifamily":
        sq_ft = rng.randint(18000, 220000)
        return {
            "property_subtype": rng.choice(["garden", "midrise", "highrise", "build_to_rent"]),
            "usage_type": "residential",
            "sq_ft": sq_ft,
            "price_per_sq_ft": f"{rng.randint(28, 64)}.00",
            "occupancy_pct": f"{rng.randint(78, 99)}.00",
        }
    if property_type == "land":
        lot_size_sq_ft = rng.randint(12000, 900000)
        return {
            "property_subtype": rng.choice(["development_site", "industrial_outdoor_storage", "infill_land", "mixed_use_site"]),
            "usage_type": "development",
            "sq_ft": None,
            "price_per_sq_ft": f"{rng.randint(18, 120)}.00",
            "lot_size_sq_ft": lot_size_sq_ft,
            "lot_size_acres": f"{lot_size_sq_ft / 43560:.4f}",
        }
    sq_ft = rng.randint(2500, 150000)
    return {
        "property_subtype": rng.choice(["specialty", "urban", "campus", "adaptive_reuse", "purpose_built"]),
        "usage_type": property_type,
        "sq_ft": sq_ft,
        "price_per_sq_ft": f"{rng.randint(34, 92)}.00",
    }


def _map_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lng:.6f}"


def _availability_for_status(status: str, index: int) -> tuple[str, str]:
    if status == "available":
        return "Immediate", "2026-05-19"
    if status == "coming_soon":
        month = 7 + (index % 5)
        return f"Q{((month - 1) // 3) + 1} 2026", date(2026, month, 1).isoformat()
    if status == "pipeline":
        return "Pipeline delivery", "2027-03-01"
    if status == "under_offer":
        return "Under offer", "2026-06-15"
    return status.replace("_", " ").title(), "2026-05-19"


def _select_facing(index: int, market: MarketSeed, neighborhood: str) -> str:
    default_facing = FACING_SEQUENCE[index % len(FACING_SEQUENCE)]
    if market.port_distance_miles > 8:
        return default_facing
    if neighborhood in COASTAL_FACING_NEIGHBORHOODS:
        return COASTAL_FACING_SEQUENCE[index % len(COASTAL_FACING_SEQUENCE)]
    if market.port_distance_miles <= 4 and index % 8 == 0:
        return COASTAL_FACING_SEQUENCE[index % len(COASTAL_FACING_SEQUENCE)]
    return default_facing


def _coastal_facing_note(facing: str) -> str | None:
    return COASTAL_FACING_NOTES.get(facing)


def _synthetic_cap_rate(property_type: str, status: str, index: int, rng: random.Random) -> Decimal | None:
    if status in {"sold", "withdrawn", "pipeline"}:
        return None

    bounds_by_type: dict[str, tuple[str, str]] = {
        "industrial": ("0.0510", "0.0735"),
        "office": ("0.0540", "0.0810"),
        "retail": ("0.0480", "0.0775"),
        "multifamily": ("0.0410", "0.0610"),
        "mixed_use": ("0.0500", "0.0710"),
        "hospitality": ("0.0620", "0.0910"),
        "medical": ("0.0460", "0.0660"),
        "life_science": ("0.0430", "0.0600"),
        "data_center": ("0.0420", "0.0580"),
        "self_storage": ("0.0520", "0.0740"),
        "senior_housing": ("0.0500", "0.0680"),
        "student_housing": ("0.0470", "0.0640"),
    }
    bounds = bounds_by_type.get(property_type)
    if bounds is None:
        return None

    lower_bound = Decimal(bounds[0])
    upper_bound = Decimal(bounds[1])
    spread = upper_bound - lower_bound
    offset = Decimal(rng.randint(0, 1000)) / Decimal("1000")
    seasonal_tilt = Decimal((index % 7) - 3) * Decimal("0.0006")
    cap_rate = lower_bound + (spread * offset) + seasonal_tilt
    return cap_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _row_payload(index: int, market: MarketSeed, rng: random.Random) -> dict[str, Any]:
    property_type = PROPERTY_TYPE_SEQUENCE[index % len(PROPERTY_TYPE_SEQUENCE)]
    status = STATUS_SEQUENCE[index % len(STATUS_SEQUENCE)]
    profile = _property_type_profile(property_type, rng)
    neighborhood = market.neighborhoods[index % len(market.neighborhoods)]
    submarket = f"{market.market} - {neighborhood}"
    street = f"{rng.randint(10, 9800)} {rng.choice(STREET_NAMES)} {rng.choice(STREET_SUFFIXES)}"
    lat = market.lat + rng.uniform(-0.09, 0.09)
    lng = market.lng + rng.uniform(-0.09, 0.09)
    availability, availability_date = _availability_for_status(status, index)
    facing = _select_facing(index, market, neighborhood)
    coastal_facing_note = _coastal_facing_note(facing)
    listing_id = f"LC-{market.country_code}-{index + 1:04d}"
    rent_currency = "USD" if market.country_code in {"US", "CA"} else ("GBP" if market.country_code == "GB" else "EUR")
    sq_ft = profile.get("sq_ft")
    cap_rate = _synthetic_cap_rate(property_type, status, index, rng)
    transaction_mode = "sale" if cap_rate is not None else ("sale" if property_type in {"land", "parking"} and index % 2 == 0 else "lease")
    sale_price = Decimal(str((sq_ft or profile.get("lot_size_sq_ft") or 10000) * rng.randint(150, 950)))
    if cap_rate is not None:
        synthetic_noi = (sale_price * cap_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        synthetic_noi = None
    additional_information = (
        "Deterministic demo enrichment: public geospatial-style address/locality backbone, synthetic CRE commercial profile, "
        f"review focus on {profile['usage_type']} use in {submarket}."
    )
    if coastal_facing_note:
        additional_information = f"{additional_information} {coastal_facing_note}"
    infrastructure_json = {
        "nearest_highway": market.highways[index % len(market.highways)],
        "airport_distance_miles": round(market.airport_distance_miles + rng.uniform(-2.0, 4.0), 2),
        "port_distance_miles": round(max(1.0, market.port_distance_miles + rng.uniform(-3.0, 7.0)), 2),
        "fiber_available": index % 3 != 0,
        "ev_charging": index % 4 == 0,
        "sprinklered": property_type in {"industrial", "cold_storage", "data_center", "self_storage"},
    }
    amenities_json = {
        "facing": facing,
        "furnishing_status": FURNISHING_SEQUENCE[index % len(FURNISHING_SEQUENCE)],
        "transit_score": 35 + (index % 60),
    }
    if coastal_facing_note:
        amenities_json["waterfront_context"] = coastal_facing_note
    financials_json = {
        "transaction_mode": transaction_mode,
        "currency": rent_currency,
        "synthetic_benchmark": True,
        "cap_rate": str(cap_rate) if cap_rate is not None else None,
        "stabilized_noi": str(synthetic_noi) if synthetic_noi is not None else None,
    }
    source_metadata_json = {
        "public_research_sources": ["OpenAddresses", "GeoNames", "Microsoft Global ML Building Footprints"],
        "geospatial_backbone": "deterministic_demo_seed_after_public_dataset_research",
        "commercial_profile": "synthetic_cre_profile",
        "license_note": "Generated demo row; not a real market listing.",
    }
    return {
        "listing_id": listing_id,
        "external_source_id": f"seed-{index + 1:04d}",
        "source_dataset": "deterministic_public_geography_backbone",
        "property_name": f"{neighborhood} {profile['property_subtype'].replace('_', ' ').title()} {index + 1}",
        "address": f"{street}, {market.city}",
        "property_type": property_type,
        "property_subtype": profile["property_subtype"],
        "asset_class": property_type,
        "usage_type": profile["usage_type"],
        "zoning": rng.choice(["commercial", "industrial", "mixed_use", "residential", "special_purpose"]),
        "tenure": rng.choice(["freehold", "leasehold", "condominium", "ground_lease"]),
        "status": status,
        "status_date": "2026-05-19",
        "sq_ft": sq_ft,
        "building_area_sq_ft": sq_ft,
        "leasable_area_sq_ft": sq_ft,
        "lot_size_sq_ft": profile.get("lot_size_sq_ft"),
        "lot_size_acres": profile.get("lot_size_acres"),
        "price_per_sq_ft": profile["price_per_sq_ft"],
        "price_basis": "annual_rent",
        "asking_rent": profile["price_per_sq_ft"],
        "asking_rent_period": "annual_psf",
        "rent_currency": rent_currency,
        "price_currency": rent_currency,
        "sale_price": str(sale_price),
        "cap_rate": str(cap_rate) if cap_rate is not None else None,
        "lease_type": rng.choice(["nnn", "gross", "modified_gross", "full_service"]),
        "availability": availability,
        "availability_date": availability_date,
        "available_from": availability_date,
        "vacancy_status": "vacant" if status in {"available", "coming_soon"} else "occupied",
        "occupancy_status": "available" if status in {"available", "coming_soon"} else status,
        "market": market.market,
        "country_code": market.country_code,
        "country": market.country,
        "region": market.region,
        "state_province": market.state_province,
        "county_district": f"{market.city} District",
        "city": market.city,
        "locality": neighborhood,
        "neighborhood": neighborhood,
        "submarket": submarket,
        "postal_code": f"{rng.randint(10000, 99999)}" if market.country_code == "US" else f"{market.country_code}-{rng.randint(1000, 9999)}",
        "timezone": market.timezone,
        "geo_lat": f"{lat:.6f}",
        "geo_lng": f"{lng:.6f}",
        "geocode_source": "deterministic_public_dataset_seed",
        "geocode_confidence": "0.8200",
        "map_url": _map_url(lat, lng),
        "floor_number": profile.get("floor_number"),
        "floor_count": profile.get("floor_count"),
        "year_built": rng.randint(1965, 2024),
        "year_renovated": rng.choice([None, rng.randint(2005, 2026)]),
        "ceiling_height_ft": profile.get("ceiling_height_ft"),
        "clear_height_ft": profile.get("clear_height_ft"),
        "dock_doors": profile.get("dock_doors"),
        "drive_in_doors": profile.get("drive_in_doors"),
        "truck_court_depth_ft": profile.get("truck_court_depth_ft"),
        "trailer_parking_spaces": profile.get("trailer_parking_spaces"),
        "parking_spaces": profile.get("parking_spaces") or rng.randint(8, 700),
        "parking_ratio": profile.get("parking_ratio"),
        "elevators": profile.get("elevators"),
        "frontage_ft": profile.get("frontage_ft"),
        "facing": amenities_json["facing"],
        "furnishing_status": amenities_json["furnishing_status"],
        "condition_grade": rng.choice(["A", "B+", "B", "C", "new_delivery"]),
        "energy_rating": rng.choice(["A", "B", "C", "D", "unknown"]),
        "green_certification": rng.choice([None, "LEED Silver", "BREEAM Very Good", "ENERGY STAR"]),
        "accessibility_features": rng.choice(["ADA route", "step-free access", "lift served", "curb ramp access"]),
        "loading_access": profile.get("loading_access"),
        "yard_area_sq_ft": profile.get("yard_area_sq_ft"),
        "cold_storage": property_type == "cold_storage" or profile.get("property_subtype") == "cold_storage",
        "sprinklered": infrastructure_json["sprinklered"],
        "hvac_type": rng.choice(["central", "split_system", "evaporative", "vrf", "none_reported"]),
        "power_capacity": rng.choice(["400A", "800A", "1200A", "2MW", "5MW"]),
        "floor_load_psf": rng.choice([80, 100, 125, 150, 250]),
        "nearest_highway": infrastructure_json["nearest_highway"],
        "highway_distance_miles": f"{rng.uniform(0.2, 6.0):.2f}",
        "airport_distance_miles": f"{infrastructure_json['airport_distance_miles']:.2f}",
        "port_distance_miles": f"{infrastructure_json['port_distance_miles']:.2f}",
        "rail_access": rng.choice(["nearby_intermodal", "freight_spur_possible", "metro_adjacent", "none_reported"]),
        "transit_score": amenities_json["transit_score"],
        "public_transit_notes": f"Transit access benchmarked for {neighborhood}.",
        "bike_parking": index % 5 == 0,
        "ev_charging": infrastructure_json["ev_charging"],
        "fiber_available": infrastructure_json["fiber_available"],
        "additional_information": additional_information,
        "amenities_json": amenities_json,
        "infrastructure_json": infrastructure_json,
        "financials_json": financials_json,
        "tags_json": {
            "tags": [
                property_type,
                profile["usage_type"],
                status,
                neighborhood,
                facing,
                *(["coastal_context"] if coastal_facing_note else []),
            ]
        },
        "source_metadata_json": source_metadata_json,
        "source_page": None,
        "source_row": None,
        "extraction_method": "synthetic_cre_profile",
        "confidence": "0.8500",
        "source_authority_score": "0.2800",
        "freshness_score": "0.3000",
        "duplicate_group_key": f"{listing_id}|{property_type}",
    }


def _csv_row(property_payload: dict[str, Any]) -> dict[str, str]:
    row: dict[str, str] = {}
    for field_name in CSV_FIELDNAMES:
        value = property_payload.get(field_name)
        if isinstance(value, (dict, list)):
            row[field_name] = json.dumps(value, sort_keys=True)
        elif value is None:
            row[field_name] = ""
        else:
            row[field_name] = str(value)
    return row


def _manifest_property(property_payload: dict[str, Any], *, source_row: int) -> dict[str, Any]:
    payload = dict(property_payload)
    payload["source_row"] = source_row
    payload["chunk_index"] = 0
    return payload


def _shard_name(index: int) -> tuple[str, str, str]:
    shards = (
        ("LC1", "global-cre-corpus-us-1.csv", "Global CRE Corpus - US 1"),
        ("LC2", "global-cre-corpus-us-2.csv", "Global CRE Corpus - US 2"),
        ("LC3", "global-cre-corpus-europe-1.csv", "Global CRE Corpus - Europe 1"),
        ("LC4", "global-cre-corpus-europe-2.csv", "Global CRE Corpus - Europe 2"),
    )
    return shards[index]


def _chunk_rows(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    shard_size = max(1, len(rows) // 4)
    return [rows[0:shard_size], rows[shard_size : shard_size * 2], rows[shard_size * 2 : shard_size * 3], rows[shard_size * 3 :]]


def build_large_corpus(sample_data_dir: Path, *, row_count: int = DEFAULT_ROW_COUNT, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    if row_count < 2000 or row_count > 3000:
        raise ValueError("row_count must be between 2000 and 3000")

    rng = random.Random(seed)
    files_dir = sample_data_dir / "files"
    generated_dir = sample_data_dir / "generated"
    files_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    markets = _weighted_markets(row_count)
    rows = [_row_payload(index, market, rng) for index, market in enumerate(markets)]
    rng.shuffle(rows)

    sources: list[dict[str, Any]] = []
    shard_reports: list[dict[str, Any]] = []
    for shard_index, shard_rows in enumerate(_chunk_rows(rows)):
        source_id, file_name, title = _shard_name(shard_index)
        file_path = files_dir / file_name
        with file_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
            for property_payload in shard_rows:
                writer.writerow(_csv_row(property_payload))

        source_row_offset = 2
        source = {
            "source_id": source_id,
            "source_type": "csv",
            "posted_at": datetime(2026, 5, 19, 12, shard_index, tzinfo=timezone.utc).isoformat(),
            "slack_user_id": "U_DATA_OPS",
            "slack_user_name": "Data Ops",
            "file_name": file_name,
            "file_mime_type": "text/csv",
            "source_url": None,
            "local_path": f"files/{file_name}",
            "chunks": [
                {
                    "chunk_index": 0,
                    "text": f"{title}: deterministic generated CRE corpus shard with {len(shard_rows)} rich structured rows. See source_row on each property record for CSV row provenance.",
                    "section_name": title,
                    "metadata": {
                        "generated_corpus": True,
                        "row_count": len(shard_rows),
                        "seed": seed,
                    },
                }
            ],
            "properties": [
                _manifest_property(property_payload, source_row=source_row_offset + row_index)
                for row_index, property_payload in enumerate(shard_rows)
            ],
        }
        sources.append(source)
        shard_reports.append({"file_name": file_name, "row_count": len(shard_rows), "title": title})

    manifest = {
        "team_id": "T_CRE_DEMO",
        "channel_id": "C_CRE_LISTINGS_DEMO",
        "channel_name": "cre-listings-demo",
        "sources": sources,
    }
    manifest_path = generated_dir / "import-manifest-large-corpus.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    property_type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    country_counts: dict[str, int] = {}
    for row in rows:
        property_type_counts[str(row["property_type"])] = property_type_counts.get(str(row["property_type"]), 0) + 1
        status_counts[str(row["status"])] = status_counts.get(str(row["status"]), 0) + 1
        country_counts[str(row["country_code"])] = country_counts.get(str(row["country_code"]), 0) + 1

    report = {
        "status": "generated",
        "row_count": len(rows),
        "seed": seed,
        "manifest_path": str(manifest_path),
        "shards": shard_reports,
        "property_type_counts": dict(sorted(property_type_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "country_counts": dict(sorted(country_counts.items())),
        "coordinate_coverage": len([row for row in rows if row.get("geo_lat") and row.get("geo_lng")]),
        "map_url_coverage": len([row for row in rows if row.get("map_url")]),
        "cap_rate_coverage": len([row for row in rows if row.get("cap_rate") is not None]),
        "additional_information_coverage": len([row for row in rows if row.get("additional_information")]),
    }
    report_path = generated_dir / "large-corpus-quality-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


__all__ = ["DEFAULT_ROW_COUNT", "DEFAULT_SEED", "build_large_corpus"]