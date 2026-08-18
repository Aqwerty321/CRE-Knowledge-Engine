"""Standalone Gmail + Google Sheets CRE demo backend."""

from gmail_demo.service import (
    compose_property_query_reply,
    compose_requirement_reply,
    describe_demo_contract,
    match_requirement,
    search_property_knowledge,
    validate_listing_event,
    validate_property_delete,
    validate_requirement_event,
)

__all__ = [
    "compose_property_query_reply",
    "compose_requirement_reply",
    "describe_demo_contract",
    "match_requirement",
    "search_property_knowledge",
    "validate_listing_event",
    "validate_property_delete",
    "validate_requirement_event",
]
