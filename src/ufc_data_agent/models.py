from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Event:
    event_id: str
    name: str
    event_date: str | None
    location: str | None
    status: str
    source_url: str


@dataclass(slots=True)
class Fighter:
    fighter_id: str
    name: str
    nickname: str | None = None
    height_in: float | None = None
    reach_in: float | None = None
    stance: str | None = None
    dob: str | None = None
    wins: int | None = None
    losses: int | None = None
    draws: int | None = None
    source_url: str | None = None


@dataclass(slots=True)
class Fight:
    fight_id: str
    event_id: str
    fighter_red_id: str
    fighter_blue_id: str
    winner_id: str | None
    weight_class: str | None
    method: str | None
    method_details: str | None
    round: int | None
    time: str | None
    time_format: str | None
    referee: str | None
    bout_order: int
    source_url: str


@dataclass(slots=True)
class RoundStat:
    fight_id: str
    fighter_id: str
    round: int
    knockdowns: int | None = None
    sig_str_landed: int | None = None
    sig_str_attempted: int | None = None
    total_str_landed: int | None = None
    total_str_attempted: int | None = None
    takedowns_landed: int | None = None
    takedowns_attempted: int | None = None
    submissions: int | None = None
    reversals: int | None = None
    control_seconds: int | None = None
    head_landed: int | None = None
    head_attempted: int | None = None
    body_landed: int | None = None
    body_attempted: int | None = None
    leg_landed: int | None = None
    leg_attempted: int | None = None
    distance_landed: int | None = None
    distance_attempted: int | None = None
    clinch_landed: int | None = None
    clinch_attempted: int | None = None
    ground_landed: int | None = None
    ground_attempted: int | None = None


@dataclass(slots=True)
class FightBundle:
    fight: Fight
    fighters: list[Fighter] = field(default_factory=list)
    round_stats: list[RoundStat] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

