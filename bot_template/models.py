"""Serializable contracts shared by UI, storage, and delivery."""
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Media:
    kind: str
    file_id: str


@dataclass(frozen=True)
class Button:
    text: str
    url: str | None = None
    action: str | None = None


@dataclass(frozen=True)
class Content:
    text: str = ""
    entities: list[dict[str, Any]] = field(default_factory=list)
    media: list[Media] = field(default_factory=list)
    buttons: list[list[Button]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Content":
        return cls(
            text=data.get("text", ""), entities=data.get("entities", []),
            media=[Media(**m) for m in data.get("media", [])],
            buttons=[[Button(**b) for b in row] for row in data.get("buttons", [])],
        )


@dataclass(frozen=True)
class Campaign:
    id: int
    owner_id: int
    content: Content
    status: str
    audience: str | None
    audience_filter: str | None
    scheduled_at: str | None
    revision: int
    created_at: str
    label: str = ""


@dataclass(frozen=True)
class Delivery:
    id: int
    campaign_id: int
    user_id: int
    next_part: int
    attempts: int
    claim_token: str
