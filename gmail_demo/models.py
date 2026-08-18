from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _split_values(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[,;|]", str(value))
    return [str(item).strip().lower() for item in values if str(item).strip()]


class FeatureState(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class PropertyRow(BaseModel):
    """One row in the demo Properties worksheet."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    property_id: str | None = None
    property_name: str = Field(min_length=1)
    address: str | None = None
    city: str | None = "Austin"
    submarket: str | None = None
    property_type: str | None = None
    suite: str | None = None
    available_sf: int = Field(gt=0)
    min_divisible_sf: int | None = Field(default=None, gt=0)
    max_contiguous_sf: int | None = Field(default=None, gt=0)
    use_types: list[str] = Field(default_factory=list)
    available_from: str | None = None
    rent_psf_year: float | None = Field(default=None, ge=0)
    lease_type: str | None = None
    opex_psf_year: float | None = Field(default=None, ge=0)
    office_sf: int | None = Field(default=None, ge=0)
    clear_height_ft: float | None = Field(default=None, ge=0)
    power_amps: int | None = Field(default=None, ge=0)
    voltage: str | None = None
    hvac: FeatureState = FeatureState.UNKNOWN
    clean_room: FeatureState = FeatureState.UNKNOWN
    dock_doors: int | None = Field(default=None, ge=0)
    parking_per_1000: float | None = Field(default=None, ge=0)
    status: str = "available"
    brochure_url: str | None = None
    source_message_id: str | None = None
    source_subject: str | None = None
    updated_at: str | None = None
    notes: str | None = None

    @field_validator("use_types", mode="before")
    @classmethod
    def parse_use_types(cls, value: Any) -> list[str]:
        return _split_values(value)

    @field_validator("hvac", "clean_room", mode="before")
    @classmethod
    def parse_feature_state(cls, value: Any) -> str:
        if value is None or value == "":
            return FeatureState.UNKNOWN.value
        if isinstance(value, bool):
            return FeatureState.YES.value if value else FeatureState.NO.value
        normalized = str(value).strip().lower()
        if normalized in {
            "true",
            "y",
            "yes",
            "full",
            "full hvac",
            "100% hvac",
            "fully hvac",
            "existing",
            "existing clean room",
            "confirmed",
        }:
            return FeatureState.YES.value
        if normalized in {"false", "n", "no", "none", "no hvac", "no clean room", "not available"}:
            return FeatureState.NO.value
        return FeatureState.UNKNOWN.value

    @field_validator(
        "min_divisible_sf",
        "max_contiguous_sf",
        "rent_psf_year",
        "opex_psf_year",
        "office_sf",
        "clear_height_ft",
        "power_amps",
        "dock_doors",
        "parking_per_1000",
        mode="before",
    )
    @classmethod
    def empty_numeric_is_none(cls, value: Any) -> Any:
        return None if value in {None, ""} else value

    @model_validator(mode="after")
    def fill_size_defaults(self) -> "PropertyRow":
        if self.min_divisible_sf is None:
            self.min_divisible_sf = self.available_sf
        if self.max_contiguous_sf is None:
            self.max_contiguous_sf = self.available_sf
        return self


class TenantRequirement(BaseModel):
    """Normalized tenant requirement extracted by the Toolhouse worker."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    requirement_id: str | None = None
    source_message_id: str | None = None
    source_thread_id: str | None = None
    source_subject: str = Field(min_length=1)
    requester_name: str | None = None
    requester_email: str | None = None
    size_min_sf: int = Field(gt=0)
    size_max_sf: int = Field(gt=0)
    city: str | None = "Austin"
    submarkets: list[str] = Field(default_factory=list)
    property_types: list[str] = Field(default_factory=list)
    use_types: list[str] = Field(default_factory=list)
    required_features: list[str] = Field(default_factory=list)
    preferred_features: list[str] = Field(default_factory=list)
    min_power_amps: int | None = Field(default=None, ge=0)
    needs_clean_room: bool = False
    needs_full_hvac: bool = False
    move_in_by: str | None = None
    notes: str | None = None

    @field_validator(
        "submarkets",
        "property_types",
        "use_types",
        "required_features",
        "preferred_features",
        mode="before",
    )
    @classmethod
    def parse_lists(cls, value: Any) -> list[str]:
        return _split_values(value)

    @field_validator("min_power_amps", mode="before")
    @classmethod
    def empty_power_is_none(cls, value: Any) -> Any:
        return None if value in {None, ""} else value

    @model_validator(mode="after")
    def validate_size_range(self) -> "TenantRequirement":
        if self.size_max_sf < self.size_min_sf:
            raise ValueError("size_max_sf must be greater than or equal to size_min_sf")
        hard_markers = ("required", "must", "need", "minimum")
        soft_markers = ("acceptable", "considered", "preferred", "nice to have", "optional")
        hard_features: list[str] = []
        soft_features = list(self.preferred_features)
        for feature in self.required_features:
            normalized = feature.casefold()
            is_explicitly_soft = any(marker in normalized for marker in soft_markers)
            is_explicitly_hard = any(marker in normalized for marker in hard_markers)
            target = soft_features if is_explicitly_soft and not is_explicitly_hard else hard_features
            if feature not in target:
                target.append(feature)
        self.required_features = hard_features
        self.preferred_features = list(dict.fromkeys(soft_features))
        return self


class ListingEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    event_type: Literal["listing_update"] = "listing_update"
    operation: Literal["create", "update", "upsert"] = "upsert"
    source_message_id: str = Field(min_length=1)
    source_thread_id: str | None = None
    source_subject: str = Field(min_length=1)
    sender_email: str | None = None
    received_at: str | None = None
    properties: list[PropertyRow] = Field(min_length=1)


class PropertyDeleteTarget(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    property_id: str | None = None
    property_name: str | None = None
    suite: str | None = None

    @model_validator(mode="after")
    def require_stable_id_or_identity(self) -> "PropertyDeleteTarget":
        if not self.property_id and not (self.property_name and self.suite):
            raise ValueError("provide property_id or both property_name and suite")
        return self


class PropertyDeleteEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    event_type: Literal["property_delete"] = "property_delete"
    operation: Literal["delete"] = "delete"
    source_message_id: str = Field(min_length=1)
    source_thread_id: str | None = None
    source_subject: str = Field(min_length=1)
    sender_email: str | None = None
    received_at: str | None = None
    target: PropertyDeleteTarget
    reason: str | None = None


class RequirementEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    event_type: Literal["tenant_requirement"] = "tenant_requirement"
    source_message_id: str = Field(min_length=1)
    source_thread_id: str | None = None
    source_subject: str = Field(min_length=1)
    sender_email: str | None = None
    received_at: str | None = None
    requirement: TenantRequirement


class ConstraintCheck(BaseModel):
    name: str
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    detail: str


class PropertyMatch(BaseModel):
    property: PropertyRow
    match_status: Literal["FIT", "NO_FIT", "UNKNOWN"]
    score: int
    compatible_size_min_sf: int | None = Field(default=None, gt=0)
    compatible_size_max_sf: int | None = Field(default=None, gt=0)
    checks: list[ConstraintCheck] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_compatible_size_range(self) -> "PropertyMatch":
        if (
            self.compatible_size_min_sf is not None
            and self.compatible_size_max_sf is not None
            and self.compatible_size_max_sf < self.compatible_size_min_sf
        ):
            raise ValueError("compatible_size_max_sf must be greater than or equal to compatible_size_min_sf")
        return self
