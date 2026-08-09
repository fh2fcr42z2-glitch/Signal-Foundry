import csv
from pathlib import Path

from ufc_data_agent.models import Event, Fight, FightBundle, Fighter, RoundStat
from ufc_data_agent.storage import Database


def _bundle(fight_id: str, event_id: str, winner: str, landed: int) -> FightBundle:
    fighters = [Fighter("red", "Red"), Fighter("blue", "Blue")]
    fight = Fight(
        fight_id, event_id, "red", "blue", winner, "Lightweight", "Decision", None, 3, "5:00", None, None, 1, f"https://example/{fight_id}"
    )
    stats = [RoundStat(fight_id, "red", 1, sig_str_landed=landed, sig_str_attempted=20)]
    return FightBundle(fight, fighters, stats)


def test_feature_export_is_point_in_time(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.sqlite")
    database.upsert_event(Event("e1", "First", "2024-01-01", "A", "completed", "https://example/e1"))
    database.upsert_event(Event("e2", "Second", "2024-02-01", "B", "completed", "https://example/e2"))
    database.upsert_bundle(_bundle("f1", "e1", "red", 10))
    database.upsert_bundle(_bundle("f2", "e2", "blue", 99))
    output = tmp_path / "features.csv"
    assert database.export_features(output) == 2
    rows = list(csv.DictReader(output.open()))
    assert rows[0]["red_prior_fights"] == "0"
    assert rows[1]["red_prior_fights"] == "1"
    assert rows[1]["red_sig_str_landed"] == "10"
    database.close()
