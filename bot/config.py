from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Union
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ChatId = Union[int, str]


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    token: str
    timezone_name: str
    timezone: ZoneInfo
    publish_time: time
    posts_path: Path
    images_dir: Path
    prompt_path: Path
    providers_path: Path
    image_manifest_path: Path
    state_path: Path
    inbox_path: Path
    owner_user_id: int | None
    default_channel_id: ChatId | None


def _parse_chat_id(value: str | None) -> ChatId | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if stripped.lstrip("-").isdigit():
        return int(stripped)

    return stripped


def _parse_owner_user_id(value: str | None) -> int | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if not stripped.isdigit():
        raise RuntimeError("OWNER_USER_ID must be a numeric Telegram user id.")

    return int(stripped)


def _parse_publish_time(raw_value: str) -> time:
    parts = raw_value.strip().split(":")
    if len(parts) != 2:
        raise RuntimeError("PUBLISH_TIME must be in HH:MM format.")

    hour = int(parts[0])
    minute = int(parts[1])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise RuntimeError("PUBLISH_TIME must contain a valid 24-hour time.")

    return time(hour=hour, minute=minute)


def _resolve_path(base_dir: Path, raw_value: str | None, *default_parts: str) -> Path:
    if raw_value:
        candidate = Path(raw_value.strip())
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        return candidate

    return base_dir.joinpath(*default_parts)


def load_settings() -> Settings:
    base_dir = Path(__file__).resolve().parents[1]
    load_dotenv(base_dir / ".env")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to .env before starting the bot."
        )

    timezone_name = os.getenv("TIMEZONE", "Europe/Kyiv").strip() or "Europe/Kyiv"
    publish_time = _parse_publish_time(os.getenv("PUBLISH_TIME", "20:30"))
    prompt_path = _resolve_path(
        base_dir,
        os.getenv("POST_PROMPT_PATH"),
        "content",
        "prompts",
        "post_prompt.txt",
    )
    providers_path = _resolve_path(
        base_dir,
        os.getenv("AI_PROVIDERS_PATH"),
        "config",
        "providers.json",
    )

    return Settings(
        base_dir=base_dir,
        token=token,
        timezone_name=timezone_name,
        timezone=ZoneInfo(timezone_name),
        publish_time=publish_time,
        posts_path=base_dir / "content" / "posts" / "posts.json",
        images_dir=base_dir / "content" / "images",
        prompt_path=prompt_path,
        providers_path=providers_path,
        image_manifest_path=base_dir / "content" / "images" / "manifest.json",
        state_path=base_dir / "data" / "state.json",
        inbox_path=base_dir / "data" / "inbox.jsonl",
        owner_user_id=_parse_owner_user_id(os.getenv("OWNER_USER_ID")),
        default_channel_id=_parse_chat_id(os.getenv("DEFAULT_CHANNEL_ID")),
    )
