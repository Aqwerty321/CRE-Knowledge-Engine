from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slack_sdk import WebClient


@dataclass(frozen=True)
class SlackFileSeed:
    channel_name: str
    file_name: str
    title: str


def build_default_file_seed_plan() -> list[SlackFileSeed]:
    return [
        SlackFileSeed("cre-listings", "main-street-office-flyer.pdf", "Main Street Office Flyer"),
        SlackFileSeed("cre-listings", "elm-ave-industrial-flyer.pdf", "Elm Ave Industrial Flyer"),
        SlackFileSeed("cre-listings", "downtown-office-inventory.csv", "Downtown Office Inventory"),
        SlackFileSeed("cre-listings", "industrial-availability.csv", "Industrial Availability"),
        SlackFileSeed("cre-listings", "slack-field-notes.txt", "Slack Field Notes"),
        SlackFileSeed("cre-listings", "source-corrections.csv", "Source Corrections"),
        SlackFileSeed("cre-listings", "last-mile-industrial-watchlist.csv", "Last-Mile Industrial Watchlist"),
        SlackFileSeed("cre-listings", "client-tour-notes.txt", "Client Tour Notes"),
        SlackFileSeed("cre-listings", "access-constraints-notes.txt", "Access Constraints Notes"),
        SlackFileSeed("cre-listings", "retail-office-followups.csv", "Retail And Office Follow-Ups"),
        SlackFileSeed("cre-listings", "global-cre-corpus-us-1.csv", "Global CRE Corpus - US 1"),
        SlackFileSeed("cre-listings", "global-cre-corpus-us-2.csv", "Global CRE Corpus - US 2"),
        SlackFileSeed("cre-listings", "global-cre-corpus-europe-1.csv", "Global CRE Corpus - Europe 1"),
        SlackFileSeed("cre-market-research", "q2-metro-market-snapshot.pdf", "Q2 Metro Market Snapshot"),
        SlackFileSeed("cre-market-research", "market-street-retail-brief.pdf", "Market Street Retail Brief"),
        SlackFileSeed("cre-market-research", "tenant-requirements-summary.txt", "Tenant Requirements Summary"),
        SlackFileSeed("cre-market-research", "tenant-expansion-brief.txt", "Tenant Expansion Brief"),
        SlackFileSeed("cre-market-research", "broker-availability-tracker.xlsx", "Broker Availability Tracker"),
        SlackFileSeed("cre-market-research", "global-cre-corpus-europe-2.csv", "Global CRE Corpus - Europe 2"),
        SlackFileSeed("cre-private-demo", "source-corrections.csv", "Source Corrections"),
        SlackFileSeed("cre-private-demo", "broker-availability-tracker.xlsx", "Broker Availability Tracker"),
        SlackFileSeed("cre-private-demo", "access-constraints-notes.txt", "Access Constraints Notes"),
    ]


class SlackFileSeeder:
    def __init__(self, client: WebClient) -> None:
        self.client = client
        self.seed_plan = build_default_file_seed_plan()

    def seed_workspace(
        self,
        *,
        sample_files_dir: Path,
        dry_run: bool,
        recent_limit: int,
        force_upload_matching: bool = False,
        file_names: set[str] | None = None,
    ) -> dict[str, Any]:
        selected_plan = [seed for seed in self.seed_plan if file_names is None or seed.file_name in file_names]
        if file_names is not None:
            planned_names = {seed.file_name for seed in selected_plan}
            missing = sorted(file_names - planned_names)
            if missing:
                raise ValueError(f"Unknown Slack demo file(s): {', '.join(missing)}")

        channel_names = {seed.channel_name for seed in selected_plan}
        channel_ids = self.resolve_channel_ids(channel_names)
        history_cache: dict[str, list[dict[str, Any]]] = {}
        actions: list[dict[str, Any]] = []

        for seed in selected_plan:
            file_path = sample_files_dir / seed.file_name
            if not file_path.exists():
                raise FileNotFoundError(f"Missing sample file for Slack seeding: {file_path}")

            channel_id = channel_ids[seed.channel_name]
            history = history_cache.setdefault(channel_id, self.fetch_recent_messages(channel_id, recent_limit))
            existing = self.find_matching_file_share(history, seed)
            if existing is not None and not force_upload_matching:
                actions.append(
                    {
                        "channel_name": seed.channel_name,
                        "channel_id": channel_id,
                        "file_name": seed.file_name,
                        "title": seed.title,
                        "action": "reused",
                        "file_id": str(existing.get("id") or ""),
                    }
                )
                continue

            response = self.upload_file(
                channel_id=channel_id,
                file_path=file_path,
                seed=seed,
                dry_run=dry_run,
            )
            actions.append(response)

        return {
            "status": "planned" if dry_run else "seeded",
            "dry_run": dry_run,
            "force_upload_matching": force_upload_matching,
            "file_names": [seed.file_name for seed in selected_plan],
            "channel_ids": channel_ids,
            "actions": actions,
        }

    def resolve_channel_ids(self, channel_names: set[str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        cursor: str | None = None

        while True:
            response = self.client.conversations_list(
                types="public_channel,private_channel",
                limit=1000,
                cursor=cursor,
            )
            for channel in response.get("channels", []):
                channel_name = str(channel.get("name") or "")
                if channel_name in channel_names:
                    resolved[channel_name] = str(channel.get("id") or "")

            if len(resolved) == len(channel_names):
                break

            cursor = str(response.get("response_metadata", {}).get("next_cursor") or "")
            if not cursor:
                break

        missing = sorted(channel_names - set(resolved))
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"Missing Slack channels for file seeding: {missing_text}")

        return resolved

    def fetch_recent_messages(self, channel_id: str, limit: int) -> list[dict[str, Any]]:
        response = self.client.conversations_history(channel=channel_id, limit=limit)
        return list(response.get("messages", []))

    def find_matching_file_share(self, messages: list[dict[str, Any]], seed: SlackFileSeed) -> dict[str, Any] | None:
        for message in messages:
            for file_payload in list(message.get("files", [])):
                file_name = str(file_payload.get("name") or "")
                title = str(file_payload.get("title") or "")
                if file_name == seed.file_name or title == seed.title:
                    return file_payload
        return None

    def upload_file(
        self,
        *,
        channel_id: str,
        file_path: Path,
        seed: SlackFileSeed,
        dry_run: bool,
    ) -> dict[str, Any]:
        if dry_run:
            return {
                "channel_name": seed.channel_name,
                "channel_id": channel_id,
                "file_name": seed.file_name,
                "title": seed.title,
                "action": "would_upload",
                "file_id": f"dry-run-{seed.file_name}",
            }

        response = self.client.files_upload_v2(
            channel=channel_id,
            file=str(file_path),
            filename=seed.file_name,
            title=seed.title,
        )
        file_payload = dict(response.get("file") or {})
        return {
            "channel_name": seed.channel_name,
            "channel_id": channel_id,
            "file_name": seed.file_name,
            "title": seed.title,
            "action": "uploaded",
            "file_id": str(file_payload.get("id") or ""),
        }


__all__ = ["SlackFileSeed", "SlackFileSeeder", "build_default_file_seed_plan"]