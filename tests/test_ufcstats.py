from pathlib import Path

from ufc_data_agent.sources.ufcstats import UFCStatsSource

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_event_list() -> None:
    events = UFCStatsSource.parse_event_list((FIXTURES / "events.html").read_text())
    assert [event.event_id for event in events] == ["e1", "e2"]
    assert events[0].event_date == "2024-01-02"
    assert events[0].location == "Las Vegas, Nevada"


def test_parses_fight_and_both_fighters_round_stats() -> None:
    bundle = UFCStatsSource.parse_fight_detail(
        (FIXTURES / "fight.html").read_text(),
        event_id="e1",
        fight_url="http://ufcstats.com/fight-details/f1",
    )
    assert bundle.fight.winner_id == "red1"
    assert bundle.fight.method == "Decision - Unanimous"
    assert len(bundle.round_stats) == 2
    red = next(stat for stat in bundle.round_stats if stat.fighter_id == "red1")
    assert (red.sig_str_landed, red.sig_str_attempted) == (10, 20)
    assert red.control_seconds == 90
    assert (red.head_landed, red.head_attempted) == (6, 12)

