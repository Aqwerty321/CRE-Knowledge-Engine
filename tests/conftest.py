from __future__ import annotations

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def disable_optional_local_services_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CRE_VECTOR_SEARCH_ENABLED", "false")
    monkeypatch.setenv("CRE_VECTOR_INDEX_ON_IMPORT", "false")
    monkeypatch.setenv("CRE_OCR_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
