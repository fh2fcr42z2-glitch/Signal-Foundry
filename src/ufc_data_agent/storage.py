from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .models import Event, FightBundle, Fighter

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, name TEXT NOT NULL, event_date TEXT, location TEXT,
  status TEXT NOT NULL, source_url TEXT NOT NULL, collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS fighters (
  fighter_id TEXT PRIMARY KEY, name TEXT NOT NULL, nickname TEXT, height_in REAL, reach_in REAL,
  stance TEXT, dob TEXT, wins INTEGER, losses INTEGER, draws INTEGER, source_url TEXT,
  collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS fights (
  fight_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(event_id),
  fighter_red_id TEXT NOT NULL REFERENCES fighters(fighter_id),
  fighter_blue_id TEXT NOT NULL REFERENCES fighters(fighter_id),
  winner_id TEXT REFERENCES fighters(fighter_id), weight_class TEXT, method TEXT, method_details TEXT,
  round INTEGER, time TEXT, time_format TEXT, referee TEXT, bout_order INTEGER NOT NULL,
  source_url TEXT NOT NULL, collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS round_stats (
  fight_id TEXT NOT NULL REFERENCES fights(fight_id) ON DELETE CASCADE,
  fighter_id TEXT NOT NULL REFERENCES fighters(fighter_id), round INTEGER NOT NULL,
  knockdowns INTEGER, sig_str_landed INTEGER, sig_str_attempted INTEGER,
  total_str_landed INTEGER, total_str_attempted INTEGER, takedowns_landed INTEGER,
  takedowns_attempted INTEGER, submissions INTEGER, reversals INTEGER, control_seconds INTEGER,
  head_landed INTEGER, head_attempted INTEGER, body_landed INTEGER, body_attempted INTEGER,
  leg_landed INTEGER, leg_attempted INTEGER, distance_landed INTEGER, distance_attempted INTEGER,
  clinch_landed INTEGER, clinch_attempted INTEGER, ground_landed INTEGER, ground_attempted INTEGER,
  PRIMARY KEY (fight_id, fighter_id, round)
);
CREATE TABLE IF NOT EXISTS raw_pages (
  url TEXT PRIMARY KEY, body TEXT NOT NULL, sha256 TEXT NOT NULL,
  fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS collection_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT, status TEXT NOT NULL, events_seen INTEGER NOT NULL DEFAULT 0,
  fights_seen INTEGER NOT NULL DEFAULT 0, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);
CREATE INDEX IF NOT EXISTS idx_fights_event ON fights(event_id);
CREATE INDEX IF NOT EXISTS idx_round_stats_fighter ON round_stats(fighter_id);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def start_run(self) -> int:
        cursor = self.connection.execute("INSERT INTO collection_runs(status) VALUES ('running')")
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, *, events: int, fights: int, error: str | None = None) -> None:
        self.connection.execute(
            """UPDATE collection_runs SET finished_at=CURRENT_TIMESTAMP, status=?, events_seen=?,
               fights_seen=?, error=? WHERE run_id=?""",
            ("failed" if error else "complete", events, fights, error, run_id),
        )
        self.connection.commit()

    def upsert_event(self, event: Event) -> None:
        values = asdict(event)
        columns = list(values)
        self.connection.execute(
            f"INSERT INTO events ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            "ON CONFLICT(event_id) DO UPDATE SET "
            + ",".join(f"{c}=excluded.{c}" for c in columns if c != "event_id"),
            tuple(values.values()),
        )
        self.connection.commit()

    def upsert_fighter(self, fighter: Fighter) -> None:
        values = asdict(fighter)
        columns = list(values)
        updates = ",".join(
            f"{c}=COALESCE(excluded.{c},fighters.{c})" for c in columns if c != "fighter_id"
        )
        self.connection.execute(
            f"INSERT INTO fighters ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            f"ON CONFLICT(fighter_id) DO UPDATE SET {updates}",
            tuple(values.values()),
        )
        self.connection.commit()

    def upsert_bundle(self, bundle: FightBundle) -> None:
        with self.transaction() as con:
            for fighter in bundle.fighters:
                values = asdict(fighter)
                columns = list(values)
                con.execute(
                    f"INSERT INTO fighters ({','.join(columns)}) VALUES "
                    f"({','.join('?' for _ in columns)}) ON CONFLICT(fighter_id) DO UPDATE SET "
                    + ",".join(
                        f"{c}=COALESCE(excluded.{c},fighters.{c})"
                        for c in columns
                        if c != "fighter_id"
                    ),
                    tuple(values.values()),
                )
            fight = asdict(bundle.fight)
            columns = list(fight)
            con.execute(
                f"INSERT INTO fights ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                "ON CONFLICT(fight_id) DO UPDATE SET "
                + ",".join(f"{c}=excluded.{c}" for c in columns if c != "fight_id"),
                tuple(fight.values()),
            )
            for stat in bundle.round_stats:
                values = asdict(stat)
                columns = list(values)
                con.execute(
                    f"INSERT INTO round_stats ({','.join(columns)}) VALUES "
                    f"({','.join('?' for _ in columns)}) ON CONFLICT(fight_id,fighter_id,round) "
                    "DO UPDATE SET "
                    + ",".join(
                        f"{c}=excluded.{c}"
                        for c in columns
                        if c not in {"fight_id", "fighter_id", "round"}
                    ),
                    tuple(values.values()),
                )

    def completed_event_ids(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT DISTINCT event_id FROM fights WHERE event_id IN (SELECT event_id FROM events)"
        )
        return {str(row[0]) for row in rows}

    def export_features(self, destination: Path) -> int:
        """Export pre-fight career features using only bouts before the target bout."""
        query = """
        WITH history AS (
          SELECT target.fight_id, target.event_id, target.fighter_red_id, target.fighter_blue_id,
                 target.winner_id, target.weight_class, e.event_date, side.fighter_id, side.corner,
                 COUNT(DISTINCT prior.fight_id) AS prior_fights,
                 COUNT(DISTINCT CASE WHEN prior.winner_id=side.fighter_id THEN prior.fight_id END) AS prior_wins,
                 COUNT(DISTINCT CASE WHEN prior.winner_id IS NOT NULL
                          AND prior.winner_id<>side.fighter_id THEN prior.fight_id END) AS prior_losses,
                 COALESCE(SUM(rs.sig_str_landed),0) AS prior_sig_str_landed,
                 COALESCE(SUM(rs.sig_str_attempted),0) AS prior_sig_str_attempted,
                 COALESCE(SUM(rs.takedowns_landed),0) AS prior_td_landed,
                 COALESCE(SUM(rs.takedowns_attempted),0) AS prior_td_attempted,
                 COALESCE(SUM(rs.control_seconds),0) AS prior_control_seconds
          FROM fights target JOIN events e ON e.event_id=target.event_id
          JOIN (SELECT fight_id, fighter_red_id fighter_id, 'red' corner FROM fights
                UNION ALL SELECT fight_id, fighter_blue_id, 'blue' FROM fights) side
            ON side.fight_id=target.fight_id
          LEFT JOIN fights prior ON (prior.fighter_red_id=side.fighter_id OR prior.fighter_blue_id=side.fighter_id)
            AND (SELECT event_date FROM events WHERE event_id=prior.event_id) < e.event_date
          LEFT JOIN round_stats rs ON rs.fight_id=prior.fight_id AND rs.fighter_id=side.fighter_id
          WHERE e.event_date IS NOT NULL
          GROUP BY target.fight_id, side.fighter_id, side.corner
        )
        SELECT r.fight_id,r.event_id,r.event_date,r.weight_class,r.fighter_red_id,r.fighter_blue_id,
               CASE WHEN r.winner_id=r.fighter_red_id THEN 1 WHEN r.winner_id IS NULL THEN NULL ELSE 0 END red_win,
               r.prior_fights red_prior_fights,r.prior_wins red_prior_wins,r.prior_losses red_prior_losses,
               r.prior_sig_str_landed red_sig_str_landed,r.prior_sig_str_attempted red_sig_str_attempted,
               r.prior_td_landed red_td_landed,r.prior_td_attempted red_td_attempted,
               r.prior_control_seconds red_control_seconds,
               b.prior_fights blue_prior_fights,b.prior_wins blue_prior_wins,b.prior_losses blue_prior_losses,
               b.prior_sig_str_landed blue_sig_str_landed,b.prior_sig_str_attempted blue_sig_str_attempted,
               b.prior_td_landed blue_td_landed,b.prior_td_attempted blue_td_attempted,
               b.prior_control_seconds blue_control_seconds
        FROM history r JOIN history b ON b.fight_id=r.fight_id AND b.corner='blue'
        WHERE r.corner='red' ORDER BY r.event_date,r.fight_id
        """
        rows = self.connection.execute(query).fetchall()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", newline="", encoding="utf-8") as handle:
            if not rows:
                return 0
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(dict(row) for row in rows)
        return len(rows)

    def write_jsonl(self, destination: Path) -> int:
        rows = self.connection.execute(
            "SELECT f.*, e.name event_name, e.event_date, e.location FROM fights f JOIN events e USING(event_id)"
        ).fetchall()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(dict(row), sort_keys=True) + "\n")
        return len(rows)

    def close(self) -> None:
        self.connection.close()
