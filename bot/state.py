from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json


@dataclass
class RuntimeState:
    bound_channel_id: int | str | None = None
    bound_channel_title: str | None = None
    owner_user_id: int | None = None
    owner_chat_id: int | None = None
    owner_username: str | None = None
    owner_display_name: str | None = None
    sent_slugs: list[str] = field(default_factory=list)
    last_published_local_date: str | None = None


class StateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RuntimeState:
        if not self._path.exists():
            return RuntimeState()

        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return RuntimeState(
            bound_channel_id=payload.get("bound_channel_id"),
            bound_channel_title=payload.get("bound_channel_title"),
            owner_user_id=payload.get("owner_user_id"),
            owner_chat_id=payload.get("owner_chat_id"),
            owner_username=payload.get("owner_username"),
            owner_display_name=payload.get("owner_display_name"),
            sent_slugs=payload.get("sent_slugs", []),
            last_published_local_date=payload.get("last_published_local_date"),
        )

    def save(self, state: RuntimeState) -> None:
        self._path.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
