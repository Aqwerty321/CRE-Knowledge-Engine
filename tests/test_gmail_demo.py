from __future__ import annotations

import asyncio
import csv
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gmail_demo import seed as seed_module
from gmail_demo.app import create_app
from gmail_demo.check_env import validate_environment
from gmail_demo.mcp_server import create_demo_mcp_server
from gmail_demo.seed import (
    DEFAULT_PRIMARY_EMAIL,
    DEFAULT_SECONDARY_EMAIL,
    load_email_templates,
    normalize_toolhouse_agent_url,
    normalize_toolhouse_chat_id,
    select_messages,
)
from gmail_demo.service import (
    compose_property_query_reply,
    compose_requirement_reply,
    describe_demo_contract,
    get_seed_properties,
    match_requirement,
    search_property_knowledge,
    validate_listing_event,
    validate_property_delete,
    validate_requirement_event,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_demo_environment() -> dict[str, str]:
    return {
        "GMAIL_DEMO_PRIMARY_EMAIL": "aaditya@toolhouse.ai",
        "GMAIL_DEMO_SECONDARY_EMAIL": "aadityasoni2020@gmail.com",
        "GMAIL_DEMO_MCP_TOKEN": "0" * 48,
        "GMAIL_DEMO_PUBLIC_URL": "https://cre-demo.example.com",
        "GMAIL_DEMO_SECONDARY_APP_PASSWORD": "abcdefghijklmnop",
        "TOOLHOUSE_API_KEY": "test-toolhouse-key",
        "GMAIL_DEMO_TOOLHOUSE_CHAT_ID": "12345678-1234-1234-1234-123456789abc",
        "GMAIL_DEMO_SPREADSHEET_ID": "test-spreadsheet-id-123456789",
        "GMAIL_DEMO_SENDER_NAME": "Aaditya",
    }


def _requirement() -> dict[str, object]:
    return {
        "source_message_id": "msg-requirement-1",
        "source_thread_id": "thread-1",
        "source_subject": "10-30K SF Electronics Lab Requirement",
        "requester_name": "Kelly",
        "requester_email": "kelly@example.com",
        "size_min_sf": 10_000,
        "size_max_sf": 30_000,
        "city": "Austin",
        "property_types": ["flex"],
        "use_types": ["lab"],
        "required_features": ["clean room", "full hvac"],
        "min_power_amps": 1_000,
    }


def _properties() -> list[dict[str, object]]:
    return [
        {
            "property_id": "P-001",
            "property_name": "Atlas Flex Campus",
            "city": "Austin",
            "property_type": "flex",
            "suite": "100",
            "available_sf": 18_000,
            "min_divisible_sf": 10_000,
            "max_contiguous_sf": 18_000,
            "use_types": "lab; r&d",
            "power_amps": 1_600,
            "dock_doors": 2,
            "parking_per_1000": 5,
            "hvac": "yes",
            "clean_room": "yes",
            "status": "available",
            "rent_psf_year": 21.0,
            "lease_type": "NNN",
        },
        {
            "property_id": "P-002",
            "property_name": "Generic Flex Building",
            "city": "Austin",
            "property_type": "flex",
            "suite": "200",
            "available_sf": 20_000,
            "use_types": "lab; flex",
            "power_amps": 1_200,
            "hvac": "yes",
            "clean_room": "unknown",
            "status": "available",
        },
        {
            "property_id": "P-003",
            "property_name": "Warehouse Only",
            "city": "Austin",
            "property_type": "industrial",
            "suite": "A",
            "available_sf": 40_000,
            "use_types": "warehouse",
            "power_amps": 400,
            "hvac": "no",
            "clean_room": "no",
            "status": "available",
        },
    ]


def test_demo_contract_uses_google_sheets_as_database() -> None:
    contract = describe_demo_contract()

    assert contract["database"] == "Google Sheets only"
    assert "Properties" in contract["worksheets"]
    assert "ProcessedEmails" in contract["worksheets"]
    assert contract["idempotency_key"] == "gmail_message_id"
    assert contract["listing_row_key"] == "property_id"
    assert contract["listing_identity_lookup"] == ["property_name", "suite"]
    assert "property_delete" in contract["event_types"]
    assert "property_query" in contract["event_types"]


def test_demo_environment_checker_reports_placeholders_without_secret_values() -> None:
    assert validate_environment(_valid_demo_environment()) == []

    invalid = {**_valid_demo_environment(), "TOOLHOUSE_API_KEY": "CHANGE_ME_TOOLHOUSE_API_KEY"}
    errors = validate_environment(invalid)

    assert errors == ["TOOLHOUSE_API_KEY: missing or still contains CHANGE_ME"]
    assert "test-toolhouse-key" not in " ".join(errors)


def test_demo_seed_has_exactly_thirty_valid_property_rows() -> None:
    with (REPO_ROOT / "gmail-demo-data" / "properties.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 30
    assert len({row["property_id"] for row in rows}) == 30
    assert all(row["property_name"] and row["available_sf"] for row in rows)


def test_seed_tool_returns_all_thirty_normalized_rows() -> None:
    result = get_seed_properties()

    assert result["ok"] is True
    assert result["worksheet"] == "Properties"
    assert result["row_count"] == 30
    assert len(result["rows"]) == 30
    assert result["rows"][0]["available_sf"] == 18_000
    assert result["write_mode"] == "create_only_when_worksheet_has_zero_data_rows"


def test_email_template_package_has_exactly_ten_messages() -> None:
    text = (REPO_ROOT / "gmail-demo-data" / "email-templates.md").read_text(encoding="utf-8")

    assert len(re.findall(r"^## \d+ — ", text, flags=re.MULTILINE)) == 10
    assert "999 Legal Footer Boulevard" in text
    assert "10-30K SF Electronics Lab Requirement" in text


def test_toolhouse_prompt_is_hardcoded_and_covers_full_crud() -> None:
    prompt = (REPO_ROOT / "docs" / "toolhouse-gmail-demo-agent-prompt.md").read_text(encoding="utf-8")

    assert "1PIk6jjJTdTq2KWxEO_JLRphzkdEvIKFTo7vhabxNUTg" in prompt
    assert "Reply sender name: Aaditya" in prompt
    assert "{spreadsheet_id}" not in prompt
    assert "{sender_name}" not in prompt
    for operation in ("listing_create", "listing_update", "property_delete", "property_query"):
        assert operation in prompt
    assert "validate_property_delete" in prompt
    assert "compose_property_query_reply" in prompt


def test_live_seed_templates_use_the_exact_demo_accounts_and_query_prefix() -> None:
    messages = load_email_templates()

    assert DEFAULT_PRIMARY_EMAIL == "aaditya@toolhouse.ai"
    assert DEFAULT_SECONDARY_EMAIL == "aadityasoni2020@gmail.com"
    assert len(messages) == 10
    assert all(message.subject.startswith("[CRE-DEMO]") for message in messages)
    assert [message.sequence for message in select_messages(messages, start_at=9, limit=2)] == [9, 10]


def test_toolhouse_chat_id_accepts_uuid_or_copied_agent_url() -> None:
    chat_id = "12345678-1234-4234-9234-123456789abc"

    assert normalize_toolhouse_chat_id(chat_id) == chat_id
    assert normalize_toolhouse_chat_id(f"https://agents.toolhouse.ai/{chat_id}") == chat_id
    assert normalize_toolhouse_agent_url(chat_id) is None
    assert normalize_toolhouse_agent_url(f"https://agents.toolhouse.ai/{chat_id}") == (
        f"https://agents.toolhouse.ai/{chat_id}"
    )


def test_toolhouse_completed_but_blocked_result_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        seed_module,
        "_toolhouse_request",
        lambda *args, **kwargs: {
            "data": {"status": "completed", "last_agent_message": "Blocked: required MCP tools unavailable."}
        },
    )

    with pytest.raises(RuntimeError, match="workflow blocked"):
        seed_module.verify_toolhouse_run_result(api_key="test", run_id="test-run")


def test_toolhouse_result_read_retries_a_transient_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_request(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary read timeout")
        return {"data": {"status": "completed", "last_agent_message": "- errors: 0"}}

    monkeypatch.setattr(seed_module, "_toolhouse_request", fake_request)
    monkeypatch.setattr(seed_module.time, "sleep", lambda seconds: None)

    seed_module.verify_toolhouse_run_result(api_key="test", run_id="test-run")

    assert calls == 2


def test_toolhouse_completed_with_reported_errors_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        seed_module,
        "_toolhouse_request",
        lambda *args, **kwargs: {
            "data": {"status": "completed", "last_agent_message": "Stopped with an error.\n- errors: 1"}
        },
    )

    with pytest.raises(RuntimeError, match="workflow blocked"):
        seed_module.verify_toolhouse_run_result(api_key="test", run_id="test-run")


@pytest.mark.parametrize(
    "message",
    [
        "Started.",
        "Started working.",
        "I can't complete that inspection with the tools available in this session.",
        "I can’t complete that inspection because I do not currently have Google Sheets tools.",
    ],
)
def test_toolhouse_non_operational_completion_is_a_failure(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    monkeypatch.setattr(
        seed_module,
        "_toolhouse_request",
        lambda *args, **kwargs: {"data": {"status": "completed", "last_agent_message": message}},
    )

    with pytest.raises(RuntimeError, match="workflow blocked"):
        seed_module.verify_toolhouse_run_result(api_key="test", run_id="test-run")


def test_agent_run_receives_sheet_and_sender_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(
        url: str,
        *,
        api_key: str,
        method: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        requests.append((url, method, payload))
        return {"data": {"id": "run-123"}}

    monkeypatch.setattr(seed_module, "_toolhouse_request", fake_request)

    run_id = seed_module.trigger_toolhouse_run(
        api_key="test-key",
        chat_id="12345678-1234-4234-9234-123456789abc",
        run_vars={"spreadsheet_id": "sheet-123", "sender_name": "Aaditya"},
    )

    assert run_id == "run-123"
    assert requests == [
        (
            seed_module.TOOLHOUSE_AGENT_RUNS_URL,
            "POST",
            {
                "chat_id": "12345678-1234-4234-9234-123456789abc",
                "vars": {"spreadsheet_id": "sheet-123", "sender_name": "Aaditya"},
            },
        )
    ]


def test_chat_id_run_is_verified_after_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(seed_module, "trigger_toolhouse_run", lambda **kwargs: "run-123")
    monkeypatch.setattr(
        seed_module,
        "wait_for_toolhouse_run",
        lambda **kwargs: calls.append(("wait", kwargs["run_id"])) or "completed",
    )
    monkeypatch.setattr(seed_module, "_toolhouse_run_needs_configuration", lambda **kwargs: False)
    monkeypatch.setattr(
        seed_module,
        "verify_toolhouse_run_result",
        lambda **kwargs: calls.append(("verify", kwargs["run_id"])),
    )

    result = seed_module.run_toolhouse_and_wait(
        api_key="test-key",
        chat_id_or_agent_url="12345678-1234-4234-9234-123456789abc",
        timeout_seconds=10,
        run_vars={"spreadsheet_id": "sheet-123", "sender_name": "Aaditya"},
    )

    assert result == "run-123"
    assert calls == [("wait", "run-123"), ("verify", "run-123")]


def test_published_agent_receives_exact_execution_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_endpoint(**kwargs: object) -> str:
        captured.update(kwargs)
        return "run-agent-123"

    monkeypatch.setattr(seed_module, "run_toolhouse_agent_endpoint", fake_endpoint)
    monkeypatch.setattr(seed_module, "_toolhouse_run_needs_configuration", lambda **kwargs: False)
    monkeypatch.setattr(seed_module, "verify_toolhouse_run_result", lambda **kwargs: None)

    result = seed_module.run_toolhouse_and_wait(
        api_key="test-key",
        chat_id_or_agent_url="https://agents.toolhouse.ai/12345678-1234-4234-9234-123456789abc",
        timeout_seconds=10,
        agent_message="Process only CREATE 101.",
    )

    assert result == "run-agent-123"
    assert captured["message"] == "Process only CREATE 101."


def test_chat_id_run_recovers_a_legacy_placeholder_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(seed_module, "trigger_toolhouse_run", lambda **kwargs: "run-legacy")
    monkeypatch.setattr(
        seed_module,
        "wait_for_toolhouse_run",
        lambda **kwargs: calls.append("wait") or "completed",
    )
    monkeypatch.setattr(seed_module, "_toolhouse_run_needs_configuration", lambda **kwargs: True)
    monkeypatch.setattr(
        seed_module,
        "_continue_toolhouse_run_with_configuration",
        lambda **kwargs: calls.append("continue"),
    )
    monkeypatch.setattr(
        seed_module,
        "verify_toolhouse_run_result",
        lambda **kwargs: calls.append("verify"),
    )

    result = seed_module.run_toolhouse_and_wait(
        api_key="test-key",
        chat_id_or_agent_url="12345678-1234-4234-9234-123456789abc",
        timeout_seconds=10,
        run_vars={"spreadsheet_id": "sheet-123", "sender_name": "Aaditya"},
    )

    assert result == "run-legacy"
    assert calls == ["wait", "continue", "verify"]


def test_seed_sheet_produces_multiple_confirmed_lab_matches() -> None:
    with (REPO_ROOT / "gmail-demo-data" / "properties.csv").open(newline="", encoding="utf-8") as handle:
        properties = list(csv.DictReader(handle))

    result = match_requirement(_requirement(), properties, limit=10)

    assert result["ok"] is True
    assert result["counts"]["FIT"] >= 5
    assert result["matches"][0]["match_status"] == "FIT"


def test_listing_validation_returns_sheet_rows_and_source_ids() -> None:
    result = validate_listing_event(
        {
            "event_type": "listing_update",
            "source_message_id": "msg-listing-1",
            "source_thread_id": "thread-listing-1",
            "source_subject": "Atlas availability",
            "received_at": "2026-08-14T09:00:00Z",
            "properties": [
                {
                    "property_name": "Atlas Flex Campus",
                    "suite": "100",
                    "available_sf": "18000",
                    "use_types": "lab; r&d",
                    "hvac": "full",
                    "clean_room": "existing",
                }
            ],
        }
    )

    assert result["ok"] is True
    assert result["sheet_rows"][0]["available_sf"] == 18_000
    assert result["sheet_rows"][0]["use_types"] == "lab; r&d"
    assert result["sheet_rows"][0]["source_message_id"] == "msg-listing-1"
    assert result["sheet_rows"][0]["property_id"].startswith("EMAIL-")
    assert result["row_lookup_key"] == ["property_name", "suite"]
    assert result["sheet_key_column"] == "property_id"
    assert result["sheet_headers"][0] == "property_id"


@pytest.mark.parametrize("value", ["full", "full HVAC", "100% HVAC", "confirmed"])
def test_listing_validation_normalizes_natural_language_positive_feature_states(value: str) -> None:
    result = validate_listing_event(
        {
            "event_type": "listing_update",
            "source_message_id": "msg-natural-features",
            "source_subject": "Natural feature wording",
            "properties": [
                {
                    "property_name": "Natural Language Labs",
                    "suite": "1",
                    "available_sf": 10_000,
                    "hvac": value,
                    "clean_room": "existing clean room",
                }
            ],
        }
    )

    assert result["ok"] is True
    assert result["sheet_rows"][0]["hvac"] == "yes"
    assert result["sheet_rows"][0]["clean_room"] == "yes"


def test_listing_validation_preserves_existing_property_id_for_sheet_upsert() -> None:
    event = {
        "event_type": "listing_update",
        "source_message_id": "msg-atlas-update",
        "source_subject": "Atlas update",
        "properties": [{**_properties()[0], "property_id": None, "rent_psf_year": 21.75}],
    }

    result = validate_listing_event(event, existing_properties=_properties())

    assert result["ok"] is True
    assert result["sheet_key_column"] == "property_id"
    assert result["sheet_rows"][0]["property_id"] == "P-001"
    assert result["sheet_rows"][0]["rent_psf_year"] == 21.75
    assert result["sheet_rows"][0]["source_message_id"] == "msg-atlas-update"
    assert result["sheet_rows"][0]["source_subject"] == "Atlas update"


def test_listing_validation_rejects_ambiguous_name_and_suite_identity() -> None:
    duplicate = {**_properties()[0], "property_id": "P-999"}
    event = {
        "event_type": "listing_update",
        "source_message_id": "msg-ambiguous",
        "source_subject": "Atlas update",
        "properties": [{**_properties()[0], "property_id": None}],
    }

    result = validate_listing_event(event, existing_properties=[_properties()[0], duplicate])

    assert result["ok"] is False
    assert result["error"] == "ambiguous_property_identity"
    assert set(result["matching_property_ids"]) == {"P-001", "P-999"}


def test_new_listing_property_id_is_deterministic() -> None:
    event = {
        "event_type": "listing_update",
        "source_message_id": "msg-new-listing",
        "source_subject": "New listing",
        "properties": [
            {
                "property_name": "New Flex Center",
                "suite": "A",
                "available_sf": 12_000,
            }
        ],
    }

    first = validate_listing_event(event)
    second = validate_listing_event(event)

    assert first["sheet_rows"][0]["property_id"] == second["sheet_rows"][0]["property_id"]
    assert first["sheet_rows"][0]["property_id"].startswith("EMAIL-")


def test_explicit_create_rejects_existing_property_identity() -> None:
    event = {
        "event_type": "listing_update",
        "operation": "create",
        "source_message_id": "msg-duplicate-create",
        "source_subject": "Duplicate create",
        "properties": [{**_properties()[0], "property_id": None}],
    }

    result = validate_listing_event(event, existing_properties=_properties())

    assert result["ok"] is False
    assert result["error"] == "property_already_exists"
    assert result["matching_property_ids"] == ["P-001"]


def test_explicit_update_requires_existing_property() -> None:
    event = {
        "event_type": "listing_update",
        "operation": "update",
        "source_message_id": "msg-missing-update",
        "source_subject": "Missing update",
        "properties": [
            {
                "property_name": "Missing Property",
                "suite": "404",
                "available_sf": 12_000,
            }
        ],
    }

    result = validate_listing_event(event, existing_properties=_properties())

    assert result["ok"] is False
    assert result["error"] == "property_not_found"


def test_explicit_update_by_property_id_preserves_that_key() -> None:
    event = {
        "event_type": "listing_update",
        "operation": "update",
        "source_message_id": "msg-id-update",
        "source_subject": "ID update",
        "properties": [{**_properties()[0], "rent_psf_year": 22.5}],
    }

    result = validate_listing_event(event, existing_properties=_properties())

    assert result["ok"] is True
    assert result["operation"] == "update"
    assert result["sheet_rows"][0]["property_id"] == "P-001"
    assert result["sheet_rows"][0]["rent_psf_year"] == 22.5


def test_delete_resolves_exact_identity_to_stable_property_id() -> None:
    event = {
        "event_type": "property_delete",
        "operation": "delete",
        "source_message_id": "msg-delete",
        "source_thread_id": "thread-delete",
        "source_subject": "[CRE-DEMO] Delete Atlas Suite 100",
        "target": {"property_name": "Atlas Flex Campus", "suite": "100"},
        "reason": "Listing withdrawn",
    }

    result = validate_property_delete(event, _properties())

    assert result["ok"] is True
    assert result["delete_key_column"] == "property_id"
    assert result["delete_key_value"] == "P-001"
    assert result["matched_property"]["suite"] == "100"


def test_delete_rejects_conflicting_id_and_identity() -> None:
    event = {
        "event_type": "property_delete",
        "source_message_id": "msg-delete-conflict",
        "source_subject": "[CRE-DEMO] Delete",
        "target": {
            "property_id": "P-001",
            "property_name": "Generic Flex Building",
            "suite": "200",
        },
    }

    result = validate_property_delete(event, _properties())

    assert result["ok"] is False
    assert result["error"] == "property_identity_conflict"

    typo = validate_property_delete(
        {
            "event_type": "property_delete",
            "source_message_id": "msg-delete-typo",
            "source_subject": "[CRE-DEMO] Delete",
            "target": {"property_id": "P-001", "property_name": "Atlas Typo", "suite": "100"},
        },
        _properties(),
    )
    assert typo["error"] == "property_identity_conflict"


def test_delete_rejects_missing_or_ambiguous_target() -> None:
    missing = validate_property_delete(
        {
            "event_type": "property_delete",
            "source_message_id": "msg-delete-missing",
            "source_subject": "[CRE-DEMO] Delete missing",
            "target": {"property_id": "P-404"},
        },
        _properties(),
    )
    duplicate = {**_properties()[0], "property_id": "P-999"}
    ambiguous = validate_property_delete(
        {
            "event_type": "property_delete",
            "source_message_id": "msg-delete-ambiguous",
            "source_subject": "[CRE-DEMO] Delete Atlas",
            "target": {"property_name": "Atlas Flex Campus", "suite": "100"},
        },
        [*_properties(), duplicate],
    )

    assert missing["error"] == "property_not_found"
    assert ambiguous["error"] == "ambiguous_property_delete"


def test_requirement_validation_rejects_reversed_size_range() -> None:
    event = {
        "event_type": "tenant_requirement",
        "source_message_id": "msg-1",
        "source_subject": "Requirement",
        "requirement": {**_requirement(), "size_min_sf": 30_000, "size_max_sf": 10_000},
    }

    result = validate_requirement_event(event)

    assert result["ok"] is False
    assert any(error["field"].endswith("requirement") for error in result["errors"])


def test_requirement_validation_demotes_acceptable_feature_language() -> None:
    event = {
        "event_type": "tenant_requirement",
        "source_message_id": "msg-soft-feature",
        "source_subject": "[CRE-DEMO] Requirement",
        "requirement": {
            **_requirement(),
            "required_features": ["full HVAC required", "divisible configurations are acceptable"],
            "needs_full_hvac": True,
        },
    }

    result = validate_requirement_event(event)

    assert result["ok"] is True
    assert result["requirement"]["required_features"] == ["full hvac required"]
    assert result["requirement"]["preferred_features"] == ["divisible configurations are acceptable"]


def test_acceptable_divisibility_language_does_not_downgrade_fit() -> None:
    requirement = {
        "source_message_id": "msg-soft-divisibility",
        "source_thread_id": "thread-soft-divisibility",
        "source_subject": "[CRE-DEMO] Divisible office requirement",
        "requester_email": "aadityasoni2020@gmail.com",
        "size_min_sf": 10_000,
        "size_max_sf": 16_000,
        "city": "Austin",
        "property_types": ["office"],
        "use_types": ["office"],
        "required_features": ["full HVAC required", "divisible configurations are acceptable"],
        "needs_full_hvac": True,
    }
    property_row = {
        "property_id": "P-DIV-SOFT",
        "property_name": "Divisible Office Tower",
        "suite": "500",
        "available_sf": 32_000,
        "min_divisible_sf": 16_000,
        "max_contiguous_sf": 32_000,
        "city": "Austin",
        "property_type": "office",
        "use_types": ["office"],
        "hvac": "yes",
        "status": "available",
    }

    result = match_requirement(requirement, [property_row], limit=1)

    assert result["matches"][0]["match_status"] == "FIT"
    assert all("acceptable" not in check["detail"] for check in result["matches"][0]["checks"])


def test_matcher_never_promotes_unknown_clean_room_to_fit() -> None:
    result = match_requirement(_requirement(), _properties(), limit=5)

    assert result["ok"] is True
    by_name = {item["property"]["property_name"]: item for item in result["matches"]}
    assert by_name["Atlas Flex Campus"]["match_status"] == "FIT"
    assert by_name["Generic Flex Building"]["match_status"] == "UNKNOWN"
    assert by_name["Warehouse Only"]["match_status"] == "NO_FIT"
    assert result["rule"] == "UNKNOWN is never promoted to FIT."


def test_matcher_normalizes_electronics_lab_to_explicit_lab_use() -> None:
    requirement = {**_requirement(), "use_types": ["electronics lab"]}

    result = match_requirement(requirement, _properties(), limit=5)

    assert result["ok"] is True
    by_name = {item["property"]["property_name"]: item for item in result["matches"]}
    assert by_name["Atlas Flex Campus"]["match_status"] == "FIT"
    atlas_checks = {check["name"]: check for check in by_name["Atlas Flex Campus"]["checks"]}
    assert atlas_checks["use_type"]["status"] == "PASS"


def test_matcher_deduplicates_same_property_and_suite_by_freshness() -> None:
    duplicate = {
        **_properties()[0],
        "property_id": "P-999",
        "updated_at": "2026-08-15T00:00:00Z",
        "rent_psf_year": 21.75,
    }

    result = match_requirement(_requirement(), [*_properties(), duplicate], limit=5)

    assert result["retrieval"]["input_corpus_size"] == 4
    assert result["retrieval"]["corpus_size"] == 3
    assert result["retrieval"]["duplicate_groups"][0]["selected_property_id"] == "P-999"
    atlas = [item for item in result["matches"] if item["property"]["property_name"] == "Atlas Flex Campus"]
    assert len(atlas) == 1
    assert atlas[0]["property"]["rent_psf_year"] == 21.75


def test_equivalent_required_features_create_one_check_and_one_caveat() -> None:
    requirement = {
        **_requirement(),
        "required_features": ["existing clean room", "full HVAC"],
        "needs_clean_room": True,
        "needs_full_hvac": True,
    }

    result = match_requirement(requirement, _properties(), limit=5)
    generic = next(item for item in result["matches"] if item["property"]["property_id"] == "P-002")

    assert [check["name"] for check in generic["checks"]].count("clean_room") == 1
    assert generic["caveats"].count("Clean-room capability is not confirmed.") == 1


def test_divisible_match_reply_renders_compatible_configuration() -> None:
    property_row = {
        "property_id": "P-DIV",
        "property_name": "Divisible Office Tower",
        "suite": "500",
        "available_sf": 32_000,
        "min_divisible_sf": 16_000,
        "max_contiguous_sf": 32_000,
        "city": "Austin",
        "property_type": "office",
        "use_types": ["office"],
        "hvac": "yes",
        "status": "available",
        "rent_psf_year": 33,
        "lease_type": "NNN",
    }
    requirement = {
        "source_message_id": "msg-divisible",
        "source_thread_id": "thread-divisible",
        "source_subject": "[CRE-DEMO] Divisible office requirement",
        "requester_name": "Morgan",
        "requester_email": "aadityasoni2020@gmail.com",
        "size_min_sf": 10_000,
        "size_max_sf": 16_000,
        "city": "Austin",
        "property_types": ["office"],
        "use_types": ["office"],
        "needs_full_hvac": True,
    }

    match_result = match_requirement(requirement, [property_row], limit=1)
    reply = compose_requirement_reply(requirement, match_result["matches"], sender_name="Aaditya")

    assert match_result["matches"][0]["compatible_size_min_sf"] == 16_000
    assert match_result["matches"][0]["compatible_size_max_sf"] == 16_000
    assert "16,000 SF divisible configuration within the 32,000 SF suite" in reply["body_text"]
    assert "Suite 500: 32,000 SF," not in reply["body_text"]


def test_property_knowledge_search_returns_bm25_evidence_without_vectors() -> None:
    result = search_property_knowledge(
        "Atlas electronics laboratory cleanroom with 1600 amps",
        _properties(),
        limit=2,
    )

    assert result["ok"] is True
    assert result["retrieval_mode"] == "bm25s_lexical"
    assert result["uses_embeddings"] is False
    assert result["uses_reranker"] is False
    assert result["results"][0]["property"]["property_name"] == "Atlas Flex Campus"
    assert result["results"][0]["evidence"]["evidence_id"] == "sheet:Properties:P-001"
    assert "18,000 SF" in result["results"][0]["evidence"]["snippet"]
    assert "lab" in result["results"][0]["evidence"]["matched_terms"]


def test_property_query_reply_uses_only_validated_sheet_evidence() -> None:
    search = search_property_knowledge("Atlas Suite 100 rent and power", _properties(), limit=3)

    result = compose_property_query_reply(
        query="What are the rent and power for Atlas Suite 100?",
        source_message_id="msg-query",
        source_thread_id="thread-query",
        source_subject="[CRE-DEMO] QUERY Atlas Suite 100",
        requester_email="aadityasoni2020@gmail.com",
        results=search["results"],
        sender_name="Aaditya",
    )

    assert result["ok"] is True
    assert result["send_automatically"] is True
    assert result["evidence_ids"] == ["sheet:Properties:P-001"]
    assert result["included_result_count"] == 1
    assert "18,000 SF" in result["body_text"]
    assert "minimum divisible: 10,000 SF" in result["body_text"]
    assert "$21.00/SF/year" in result["body_text"]
    assert "1,600A" in result["body_text"]
    assert "dock doors: 2" in result["body_text"]
    assert "parking: 5/1,000 SF" in result["body_text"]
    assert "Generic Flex Building" not in result["body_text"]


def test_property_query_reply_rejects_reconstructed_or_unauthorized_evidence() -> None:
    search = search_property_knowledge("Atlas", _properties(), limit=1)
    tampered = [{**search["results"][0], "evidence": {"evidence_id": "sheet:Properties:P-999"}}]

    bad_evidence = compose_property_query_reply(
        query="Atlas",
        source_message_id="msg-query",
        source_thread_id="thread-query",
        source_subject="[CRE-DEMO] QUERY Atlas",
        requester_email="aadityasoni2020@gmail.com",
        results=tampered,
    )
    bad_recipient = compose_property_query_reply(
        query="Atlas",
        source_message_id="msg-query",
        source_thread_id="thread-query",
        source_subject="[CRE-DEMO] QUERY Atlas",
        requester_email="other@example.com",
        results=search["results"],
    )

    assert bad_evidence["error"] == "invalid_property_evidence"
    assert bad_recipient["error"] == "outbound_send_not_authorized"


def test_property_query_exact_absent_identity_does_not_return_bm25_neighbors() -> None:
    search = search_property_knowledge(
        "Moonbase Omega Suite Z-9 rent size power availability",
        _properties(),
        limit=3,
    )

    result = compose_property_query_reply(
        query="What is available at Moonbase Omega Suite Z-9?",
        source_message_id="msg-moonbase",
        source_thread_id="thread-moonbase",
        source_subject="[CRE-DEMO] QUERY Moonbase Omega",
        requester_email="aadityasoni2020@gmail.com",
        results=search["results"],
        sender_name="Aaditya",
        exact_property_name="Moonbase Omega",
        exact_suite="Z-9",
    )

    assert result["ok"] is True
    assert result["included_result_count"] == 0
    assert result["evidence_ids"] == []
    assert "Moonbase Omega — Suite Z-9" in result["body_text"]
    assert "Atlas Flex Campus" not in result["body_text"]


def test_requirement_matching_includes_lexical_retrieval_receipt() -> None:
    result = match_requirement(
        {**_requirement(), "use_types": ["electronics lab"]},
        _properties(),
        limit=2,
        query="Electronics lab with an existing clean room, full HVAC, and 1,000 amps in Austin",
    )

    assert result["retrieval"]["mode"] == "bm25s_lexical_plus_structured_constraints"
    assert result["retrieval"]["uses_embeddings"] is False
    assert result["retrieval"]["uses_reranker"] is False
    assert result["matches"][0]["evidence"]["evidence_id"].startswith("sheet:Properties:")
    assert result["matches"][0]["retrieval_score"] > 0


def test_compose_reply_authorizes_full_send_only_for_the_demo_sender() -> None:
    match_result = match_requirement(_requirement(), _properties(), limit=5)
    requirement = {
        **_requirement(),
        "source_subject": "[CRE-DEMO] 10-30K SF Electronics Lab Requirement",
        "requester_email": "aadityasoni2020@gmail.com",
    }
    result = compose_requirement_reply(requirement, match_result["matches"], sender_name="Aaditya")

    assert result["ok"] is True
    assert result["action"] == "send_reply"
    assert result["from_account"] == "aaditya@toolhouse.ai"
    assert result["to"] == "aadityasoni2020@gmail.com"
    assert result["thread_id"] == "thread-1"
    assert "Atlas Flex Campus" in result["body_text"]
    assert "Generic Flex Building" in result["body_text"]
    assert "Warehouse Only" not in result["body_text"]
    assert result["requires_human_review"] is False
    assert result["send_automatically"] is True


def test_compose_reply_rejects_any_non_demo_recipient() -> None:
    match_result = match_requirement(_requirement(), _properties(), limit=5)
    requirement = {**_requirement(), "source_subject": "[CRE-DEMO] Requirement"}

    result = compose_requirement_reply(requirement, match_result["matches"], sender_name="Aaditya")

    assert result["ok"] is False
    assert result["error"] == "outbound_send_not_authorized"
    assert result["send_automatically"] is False


def test_demo_mcp_registers_only_the_nine_demo_tools() -> None:
    async def collect() -> set[str]:
        return {tool.name for tool in await create_demo_mcp_server().list_tools()}

    assert asyncio.run(collect()) == {
        "describe_demo_contract",
        "compose_property_query_reply",
        "get_seed_properties",
        "validate_listing_event",
        "validate_property_delete",
        "validate_requirement_event",
        "search_property_knowledge",
        "match_requirement",
        "compose_requirement_reply",
    }


def test_standalone_health_and_mcp_auth() -> None:
    with TestClient(create_app(token="demo-secret")) as client:
        health = client.get("/health")
        unauthorized = client.post("/toolhouse/mcp", json={})
        authorized = client.post("/toolhouse/mcp?token=demo-secret", json={})

    assert health.json() == {"status": "ok", "database": "google_sheets", "orchestrator": "toolhouse"}
    assert unauthorized.status_code == 401
    assert authorized.status_code not in {401, 421, 500, 503}
