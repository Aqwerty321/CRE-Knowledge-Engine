from __future__ import annotations

from pathlib import Path

from app.slack.demo_files import SlackFileSeeder


class FakeSlackClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, str]] = []

    def conversations_list(self, *, types: str, limit: int, cursor: str | None = None) -> dict[str, object]:
        return {
            "channels": [
                {"name": "cre-listings", "id": "C_LISTINGS"},
                {"name": "cre-market-research", "id": "C_RESEARCH"},
                {"name": "cre-private-demo", "id": "C_PRIVATE"},
            ],
            "response_metadata": {"next_cursor": ""},
        }

    def conversations_history(self, *, channel: str, limit: int) -> dict[str, object]:
        return {
            "messages": [
                {
                    "files": [
                        {
                            "id": "F_EXISTING",
                            "name": "global-cre-corpus-us-1.csv",
                            "title": "Global CRE Corpus - US 1",
                        }
                    ]
                }
            ]
        }

    def files_upload_v2(self, *, channel: str, file: str, filename: str, title: str) -> dict[str, object]:
        self.uploads.append(
            {
                "channel": channel,
                "file": file,
                "filename": filename,
                "title": title,
            }
        )
        return {"file": {"id": f"F_UPLOADED_{len(self.uploads)}"}}


def test_seed_workspace_can_force_upload_matching_files(tmp_path: Path) -> None:
    sample_files_dir = tmp_path / "files"
    sample_files_dir.mkdir()
    (sample_files_dir / "global-cre-corpus-us-1.csv").write_text("listing_id\nLC-1\n", encoding="utf-8")

    client = FakeSlackClient()
    seeder = SlackFileSeeder(client)  # type: ignore[arg-type]

    payload = seeder.seed_workspace(
        sample_files_dir=sample_files_dir,
        dry_run=False,
        recent_limit=20,
        force_upload_matching=True,
        file_names={"global-cre-corpus-us-1.csv"},
    )

    assert payload["status"] == "seeded"
    assert payload["actions"][0]["action"] == "uploaded"
    assert client.uploads[0]["filename"] == "global-cre-corpus-us-1.csv"


def test_seed_workspace_filters_to_requested_files(tmp_path: Path) -> None:
    sample_files_dir = tmp_path / "files"
    sample_files_dir.mkdir()
    (sample_files_dir / "global-cre-corpus-us-1.csv").write_text("listing_id\nLC-1\n", encoding="utf-8")

    client = FakeSlackClient()
    seeder = SlackFileSeeder(client)  # type: ignore[arg-type]

    payload = seeder.seed_workspace(
        sample_files_dir=sample_files_dir,
        dry_run=True,
        recent_limit=20,
        file_names={"global-cre-corpus-us-1.csv"},
    )

    assert payload["status"] == "planned"
    assert payload["file_names"] == ["global-cre-corpus-us-1.csv"]
    assert len(payload["actions"]) == 1