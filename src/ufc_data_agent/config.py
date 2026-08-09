from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path = Path("data/ufc.sqlite3")
    user_agent: str = "SignalFoundry-UFCResearch/0.1 (contact: configure UFC_USER_AGENT)"
    request_interval: float = 1.0
    http_timeout: float = 30.0
    max_retries: int = 4
    lookback_days: int = 45
    refresh_seconds: int = 21_600

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=Path(os.getenv("UFC_DB_PATH", "data/ufc.sqlite3")),
            user_agent=os.getenv("UFC_USER_AGENT", cls.user_agent),
            request_interval=float(os.getenv("UFC_REQUEST_INTERVAL", "1.0")),
            http_timeout=float(os.getenv("UFC_HTTP_TIMEOUT", "30")),
            max_retries=int(os.getenv("UFC_MAX_RETRIES", "4")),
            lookback_days=int(os.getenv("UFC_LOOKBACK_DAYS", "45")),
            refresh_seconds=int(os.getenv("UFC_REFRESH_SECONDS", "21600")),
        )

