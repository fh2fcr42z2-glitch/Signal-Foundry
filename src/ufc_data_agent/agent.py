from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

from .config import Settings
from .http import RespectfulClient
from .sources import UFCStatsSource
from .storage import Database

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RunResult:
    events: int = 0
    fights: int = 0
    fighters_enriched: int = 0


class UFCCollectorAgent:
    """Orchestrates incremental collection while preserving partial progress."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run_once(self, *, full: bool = False, enrich_fighters: bool = True) -> RunResult:
        database = Database(self.settings.db_path)
        run_id = database.start_run()
        result = RunResult()
        try:
            with RespectfulClient(
                user_agent=self.settings.user_agent,
                interval=self.settings.request_interval,
                timeout=self.settings.http_timeout,
                retries=self.settings.max_retries,
            ) as client:
                source = UFCStatsSource(client)
                completed_ids = set() if full else database.completed_event_ids()
                events = source.list_events("completed") + source.list_events("upcoming")
                cutoff = date.today() - timedelta(days=self.settings.lookback_days)
                for event in events:
                    database.upsert_event(event)
                    result.events += 1
                    old_event = event.event_date and date.fromisoformat(event.event_date) < cutoff
                    if event.event_id in completed_ids and old_event:
                        continue
                    LOGGER.info("Collecting %s (%s)", event.name, event.event_date or "TBA")
                    for bundle in source.collect_event(event):
                        if enrich_fighters:
                            for fighter in bundle.fighters:
                                source.enrich_fighter(fighter)
                                result.fighters_enriched += 1
                        database.upsert_bundle(bundle)
                        result.fights += 1
            database.finish_run(run_id, events=result.events, fights=result.fights)
            return result
        except Exception as exc:
            database.finish_run(run_id, events=result.events, fights=result.fights, error=str(exc))
            raise
        finally:
            database.close()

    def run_forever(self, *, full: bool = False, enrich_fighters: bool = True) -> None:
        while True:
            try:
                result = self.run_once(full=full, enrich_fighters=enrich_fighters)
                LOGGER.info("Run complete: %s", result)
            except Exception:
                LOGGER.exception("Collection run failed; progress was retained")
            time.sleep(self.settings.refresh_seconds)

