from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from slack_sdk import WebClient


@dataclass(frozen=True)
class PersonaProfile:
    display_name: str
    icon_emoji: str
    legacy_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class PersonaSeed:
    seed_key: str
    channel_name: str
    text: str
    persona_key: str | None = None
    reply_to_seed_key: str | None = None


def build_default_persona_profiles() -> dict[str, PersonaProfile]:
    return {
        "sarah": PersonaProfile(
            display_name="Sarah Lin",
            icon_emoji=":office:",
            legacy_prefixes=("Sarah", "Sarah Lin"),
        ),
        "john": PersonaProfile(
            display_name="John Park",
            icon_emoji=":construction:",
            legacy_prefixes=("John", "John Park"),
        ),
        "priya": PersonaProfile(
            display_name="Priya Raman",
            icon_emoji=":bar_chart:",
            legacy_prefixes=("Priya", "Priya Raman"),
        ),
        "maya": PersonaProfile(
            display_name="Maya Chen",
            icon_emoji=":handshake:",
            legacy_prefixes=("Maya", "Maya Chen"),
        ),
    }


def build_default_persona_seed_plan() -> list[PersonaSeed]:
    return [
        PersonaSeed(
            seed_key="listings_main_street",
            channel_name="cre-listings",
            persona_key="sarah",
            text="Uploaded the Main Street office flyer. 120 Main is still targeting Q3 2026, asking $42/SF.",
        ),
        PersonaSeed(
            seed_key="listings_union_yard",
            channel_name="cre-listings",
            persona_key="john",
            text="The Union Yard space at 64 Union Yard is available immediately. Around 31k SF, industrial, asking $24/SF.",
        ),
        PersonaSeed(
            seed_key="listings_harbor_correction",
            channel_name="cre-listings",
            persona_key="priya",
            text="Harbor Rd got updated yesterday. 240 Harbor is now 62k SF, not 58k. Use the industrial inventory as source of truth.",
        ),
        PersonaSeed(
            seed_key="listings_tenant_need",
            channel_name="cre-listings",
            persona_key="maya",
            text="Tenant wants industrial near Main with loading access, ideally under $35/SF and available soon.",
        ),
        PersonaSeed(
            seed_key="listings_beacon_watchlist",
            channel_name="cre-listings",
            persona_key="sarah",
            text="Added the last-mile watchlist: 18 Beacon Freight is immediate, 36k SF at $26/SF with two dock doors and a real truck court.",
        ),
        PersonaSeed(
            seed_key="listings_spruce_tour_note",
            channel_name="cre-listings",
            persona_key="john",
            text="Tour note: 42 Spruce Flex is under budget and has a small shared yard, but ceiling height is only 20 ft.",
        ),
        PersonaSeed(
            seed_key="listings_logistics_preference",
            channel_name="cre-listings",
            persona_key="maya",
            text="Tenant asked specifically for truck court depth and trailer parking. Beacon and Union Yard are the best in-person fits so far.",
        ),
        PersonaSeed(
            seed_key="listings_river_cold_storage",
            channel_name="cre-listings",
            persona_key="priya",
            text="Cold storage at 510 River is real, but availability slipped to September. Good economics, weaker for the near-term logistics brief.",
        ),
        PersonaSeed(
            seed_key="market_context",
            channel_name="cre-market-research",
            persona_key="maya",
            text="Uploaded the Q2 metro market snapshot and retail brief for market context and demand signals.",
        ),
        PersonaSeed(
            seed_key="market_requirements",
            channel_name="cre-market-research",
            persona_key="priya",
            text="Tenant requirements summary is attached here for recommendation and look-deeper testing.",
        ),
        PersonaSeed(
            seed_key="market_expansion_brief",
            channel_name="cre-market-research",
            persona_key="maya",
            text="Added the tenant expansion brief so the recommendation path has budget, timing, truck-court, and district preferences in one place.",
        ),
        PersonaSeed(
            seed_key="private_harbor_note",
            channel_name="cre-private-demo",
            text="Private demo note: Harbor underwriting assumptions and corrected square footage are here for internal review only.",
        ),
        PersonaSeed(
            seed_key="private_visibility_note",
            channel_name="cre-private-demo",
            text="Internal note: Keep private-demo scoped to visibility and source-controls checks during the live walkthrough.",
        ),
        PersonaSeed(
            seed_key="agent_qa_seed",
            channel_name="cre-agent-qa",
            text='QA seed: try queries like "What properties do we have available near 123 Main Street?", "Find whse opts with trk court and trlr parking.", "Which options look best for a logistics tenant under $35/SF available soon?", and "Why did you use 62k sq ft for Harbor Rd?" once ingestion is wired live.',
        ),
        PersonaSeed(
            seed_key="listings_harbor_reply",
            channel_name="cre-listings",
            persona_key="sarah",
            reply_to_seed_key="listings_harbor_correction",
            text="Thanks. I'm updating the tracker and keeping 62k SF as the current Harbor Rd figure.",
        ),
    ]


def candidate_message_texts(seed: PersonaSeed, profile: PersonaProfile | None) -> set[str]:
    candidates = {seed.text}
    if profile is None:
        return candidates

    for prefix in profile.legacy_prefixes:
        candidates.add(f"{prefix}: {seed.text}")
    return candidates


class SlackPersonaSeeder:
    def __init__(self, client: WebClient) -> None:
        self.client = client
        self.profiles = build_default_persona_profiles()
        self.seed_plan = build_default_persona_seed_plan()

    def seed_workspace(
        self,
        *,
        dry_run: bool,
        replace_legacy_prefix: bool,
        recent_limit: int,
    ) -> dict[str, Any]:
        channel_names = {seed.channel_name for seed in self.seed_plan}
        channel_ids = self.resolve_channel_ids(channel_names)
        reply_seeds_by_parent: dict[str, list[PersonaSeed]] = defaultdict(list)
        history_cache: dict[str, list[dict[str, Any]]] = {}
        thread_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        seed_timestamps: dict[str, str] = {}
        actions: list[dict[str, Any]] = []

        for seed in self.seed_plan:
            if seed.reply_to_seed_key is not None:
                reply_seeds_by_parent[seed.reply_to_seed_key].append(seed)

        top_level_seeds = [seed for seed in self.seed_plan if seed.reply_to_seed_key is None]
        reply_seeds = [seed for seed in self.seed_plan if seed.reply_to_seed_key is not None]

        for seed in top_level_seeds:
            channel_id = channel_ids[seed.channel_name]
            history = history_cache.setdefault(channel_id, self.fetch_recent_messages(channel_id, recent_limit))
            profile = self.profiles.get(seed.persona_key) if seed.persona_key else None
            match = self.find_matching_message(history, seed, profile)

            if match is not None and replace_legacy_prefix and self.is_legacy_match(match, seed, profile):
                for reply_seed in reply_seeds_by_parent.get(seed.seed_key, []):
                    replies = self.fetch_thread_replies(channel_id, str(match["ts"]), recent_limit)
                    reply_match = self.find_matching_message(
                        replies,
                        reply_seed,
                        self.profiles.get(reply_seed.persona_key) if reply_seed.persona_key else None,
                    )
                    if reply_match is not None and self.is_legacy_match(
                        reply_match,
                        reply_seed,
                        self.profiles.get(reply_seed.persona_key) if reply_seed.persona_key else None,
                    ):
                        actions.append(
                            self.delete_message(
                                channel_id=channel_id,
                                ts=str(reply_match["ts"]),
                                seed_key=reply_seed.seed_key,
                                dry_run=dry_run,
                            )
                        )
                actions.append(
                    self.delete_message(
                        channel_id=channel_id,
                        ts=str(match["ts"]),
                        seed_key=seed.seed_key,
                        dry_run=dry_run,
                    )
                )
                history_cache[channel_id] = [item for item in history if str(item.get("ts")) != str(match.get("ts"))]
                match = None

            if match is not None:
                ts = str(match.get("ts") or "")
                seed_timestamps[seed.seed_key] = ts
                actions.append(
                    {
                        "seed_key": seed.seed_key,
                        "channel_name": seed.channel_name,
                        "action": "reused",
                        "ts": ts,
                    }
                )
                continue

            response = self.post_seed_message(
                seed=seed,
                channel_id=channel_id,
                thread_ts=None,
                dry_run=dry_run,
            )
            seed_timestamps[seed.seed_key] = str(response["ts"])
            actions.append(response)
            history_cache.setdefault(channel_id, []).insert(0, {"ts": response["ts"], "text": seed.text})

        for seed in reply_seeds:
            parent_ts = seed_timestamps[seed.reply_to_seed_key or ""]
            channel_id = channel_ids[seed.channel_name]
            profile = self.profiles.get(seed.persona_key) if seed.persona_key else None
            replies: list[dict[str, Any]]

            if parent_ts.startswith("dry-run-"):
                replies = []
            else:
                replies = thread_cache.setdefault(
                    (channel_id, parent_ts),
                    self.fetch_thread_replies(channel_id, parent_ts, recent_limit),
                )

            match = self.find_matching_message(replies, seed, profile)
            if match is not None and replace_legacy_prefix and self.is_legacy_match(match, seed, profile):
                actions.append(
                    self.delete_message(
                        channel_id=channel_id,
                        ts=str(match["ts"]),
                        seed_key=seed.seed_key,
                        dry_run=dry_run,
                    )
                )
                if not dry_run:
                    replies = [item for item in replies if str(item.get("ts")) != str(match.get("ts"))]
                    thread_cache[(channel_id, parent_ts)] = replies
                match = None

            if match is not None:
                actions.append(
                    {
                        "seed_key": seed.seed_key,
                        "channel_name": seed.channel_name,
                        "action": "reused",
                        "ts": str(match.get("ts") or ""),
                        "thread_ts": parent_ts,
                    }
                )
                continue

            response = self.post_seed_message(
                seed=seed,
                channel_id=channel_id,
                thread_ts=parent_ts,
                dry_run=dry_run,
            )
            actions.append(response)

        return {
            "status": "planned" if dry_run else "seeded",
            "dry_run": dry_run,
            "replace_legacy_prefix": replace_legacy_prefix,
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
            raise ValueError(f"Missing Slack channels for persona seeding: {missing_text}")

        return resolved

    def fetch_recent_messages(self, channel_id: str, limit: int) -> list[dict[str, Any]]:
        response = self.client.conversations_history(channel=channel_id, limit=limit)
        return list(response.get("messages", []))

    def fetch_thread_replies(self, channel_id: str, thread_ts: str, limit: int) -> list[dict[str, Any]]:
        response = self.client.conversations_replies(channel=channel_id, ts=thread_ts, limit=limit)
        messages = list(response.get("messages", []))
        return [message for message in messages if str(message.get("ts")) != thread_ts]

    def find_matching_message(
        self,
        messages: list[dict[str, Any]],
        seed: PersonaSeed,
        profile: PersonaProfile | None,
    ) -> dict[str, Any] | None:
        candidates = candidate_message_texts(seed, profile)
        for message in messages:
            if str(message.get("text") or "") in candidates:
                return message
        return None

    def is_legacy_match(
        self,
        message: dict[str, Any],
        seed: PersonaSeed,
        profile: PersonaProfile | None,
    ) -> bool:
        message_text = str(message.get("text") or "")
        return message_text != seed.text and message_text in candidate_message_texts(seed, profile)

    def delete_message(self, *, channel_id: str, ts: str, seed_key: str, dry_run: bool) -> dict[str, Any]:
        if not dry_run:
            self.client.chat_delete(channel=channel_id, ts=ts)
        return {
            "seed_key": seed_key,
            "action": "would_delete" if dry_run else "deleted",
            "channel_id": channel_id,
            "ts": ts,
        }

    def post_seed_message(
        self,
        *,
        seed: PersonaSeed,
        channel_id: str,
        thread_ts: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        profile = self.profiles.get(seed.persona_key) if seed.persona_key else None
        if dry_run:
            return {
                "seed_key": seed.seed_key,
                "channel_name": seed.channel_name,
                "channel_id": channel_id,
                "action": "would_post",
                "text": seed.text,
                "ts": f"dry-run-{seed.seed_key}",
                "thread_ts": thread_ts,
                "username": profile.display_name if profile else None,
                "icon_emoji": profile.icon_emoji if profile else None,
            }

        payload: dict[str, Any] = {
            "channel": channel_id,
            "text": seed.text,
        }
        if thread_ts is not None:
            payload["thread_ts"] = thread_ts
        if profile is not None:
            payload["username"] = profile.display_name
            payload["icon_emoji"] = profile.icon_emoji

        response = self.client.chat_postMessage(**payload)
        return {
            "seed_key": seed.seed_key,
            "channel_name": seed.channel_name,
            "channel_id": channel_id,
            "action": "posted",
            "text": seed.text,
            "ts": str(response.get("ts") or ""),
            "thread_ts": thread_ts,
            "username": profile.display_name if profile else None,
            "icon_emoji": profile.icon_emoji if profile else None,
        }


__all__ = [
    "PersonaProfile",
    "PersonaSeed",
    "SlackPersonaSeeder",
    "build_default_persona_profiles",
    "build_default_persona_seed_plan",
    "candidate_message_texts",
]