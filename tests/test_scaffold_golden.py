from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ingestion.sample_importer import load_sample_manifest
from app.main import app


@pytest.mark.golden
def test_scaffold_golden_path_is_wired() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["app"] == "CRE Knowledge Engine"
    assert Path("sample-data").exists()


@pytest.mark.golden
def test_seeded_manifest_matches_demo_expectations() -> None:
    manifest = load_sample_manifest(Path("sample-data"))

    assert len(manifest.sources) == 27
    assert sum(len(source.properties) for source in manifest.sources) == 2425