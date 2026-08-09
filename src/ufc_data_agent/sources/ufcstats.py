from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from ..http import RespectfulClient
from ..models import Event, Fight, FightBundle, Fighter, RoundStat

BASE_URL = "http://ufcstats.com"


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    value = " ".join(node.get_text(" ", strip=True).split())
    return value or None


def _id_from_url(url: str | None) -> str:
    if not url:
        return ""
    query = parse_qs(urlparse(url).query)
    return next(iter(query.values()), [url.rstrip("/").rsplit("/", 1)[-1]])[0]


def _date(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _number(value: str | None) -> int | None:
    if not value or value.strip() in {"--", "---"}:
        return None
    match = re.search(r"-?\d+", value)
    return int(match.group()) if match else None


def _of(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    nums = re.findall(r"\d+", value)
    return (int(nums[0]), int(nums[1])) if len(nums) >= 2 else (None, None)


def _seconds(value: str | None) -> int | None:
    if not value or value.strip() in {"--", "---"}:
        return None
    match = re.fullmatch(r"\s*(\d+):(\d{2})\s*", value)
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


def _label_value(soup: BeautifulSoup, label: str) -> str | None:
    for item in soup.select(".b-list__box-list-item"):
        title = item.select_one(".b-list__box-item-title")
        if title and label.lower() in title.get_text(strip=True).lower():
            title.extract()
            return _text(item)
    return None


class UFCStatsSource:
    """Parser/collector for public UFCStats pages.

    Parsing methods are separate from HTTP calls so saved pages can be regression tested.
    """

    def __init__(self, client: RespectfulClient) -> None:
        self.client = client

    def list_events(self, status: str = "completed") -> list[Event]:
        url = f"{BASE_URL}/statistics/events/{status}?page=all"
        return self.parse_event_list(self.client.get_text(url), status=status)

    @staticmethod
    def parse_event_list(html: str, status: str = "completed") -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        for row in soup.select("tr.b-statistics__table-row"):
            link = row.select_one("a.b-link[href*='event-details']")
            if not link:
                continue
            cells = row.select("td")
            date_node = row.select_one(".b-statistics__date")
            location = _text(cells[-1]) if len(cells) > 1 else None
            events.append(
                Event(
                    event_id=_id_from_url(link.get("href")),
                    name=_text(link) or "Unknown event",
                    event_date=_date(_text(date_node)),
                    location=location,
                    status=status,
                    source_url=str(link.get("href")),
                )
            )
        return events

    def collect_event(self, event: Event) -> list[FightBundle]:
        html = self.client.get_text(event.source_url)
        soup = BeautifulSoup(html, "html.parser")
        bundles: list[FightBundle] = []
        for order, row in enumerate(soup.select("tr.b-fight-details__table-row[data-link]"), 1):
            fight_url = str(row.get("data-link"))
            if not fight_url:
                continue
            bundles.append(
                self.parse_fight_detail(
                    self.client.get_text(fight_url),
                    event_id=event.event_id,
                    fight_url=fight_url,
                    bout_order=order,
                    event_row=row,
                )
            )
        return bundles

    @classmethod
    def parse_fight_detail(
        cls,
        html: str,
        *,
        event_id: str,
        fight_url: str,
        bout_order: int = 1,
        event_row: Tag | None = None,
    ) -> FightBundle:
        soup = BeautifulSoup(html, "html.parser")
        fighter_links = soup.select("a.b-link.b-fight-details__person-link[href*='fighter-details']")
        if len(fighter_links) < 2:
            fighter_links = soup.select("a[href*='fighter-details']")[:2]
        if len(fighter_links) < 2:
            raise ValueError(f"Could not find both fighters on {fight_url}")
        fighters = [cls._parse_fighter_summary(soup, link, index) for index, link in enumerate(fighter_links)]
        fight_id = _id_from_url(fight_url)
        winner_id = cls._winner_id(soup, fighters)
        if event_row is not None:
            winner_id = cls._winner_from_event_row(event_row, fighters) or winner_id
        fight = Fight(
            fight_id=fight_id,
            event_id=event_id,
            fighter_red_id=fighters[0].fighter_id,
            fighter_blue_id=fighters[1].fighter_id,
            winner_id=winner_id,
            weight_class=_text(soup.select_one(".b-fight-details__fight-title")),
            method=_label_value(soup, "METHOD:"),
            method_details=_text(soup.select_one(".b-fight-details__text-item_first")),
            round=_number(_label_value(soup, "ROUND:")),
            time=_label_value(soup, "TIME:"),
            time_format=_label_value(soup, "TIME FORMAT:"),
            referee=_label_value(soup, "REFEREE:"),
            bout_order=bout_order,
            source_url=fight_url,
        )
        stats = cls._parse_round_stats(soup, fight_id, fighters)
        return FightBundle(fight=fight, fighters=fighters, round_stats=stats)

    @staticmethod
    def _winner_id(soup: BeautifulSoup, fighters: list[Fighter]) -> str | None:
        statuses = [_text(n) for n in soup.select(".b-fight-details__person-status")]
        for index, status in enumerate(statuses[:2]):
            if status and status.upper() == "W":
                return fighters[index].fighter_id
        return None

    @staticmethod
    def _winner_from_event_row(row: Tag, fighters: list[Fighter]) -> str | None:
        result_nodes = row.select(".b-flag") or row.select(".b-fight-details__table-text")[:2]
        for index, node in enumerate(result_nodes[:2]):
            if (_text(node) or "").upper() == "W":
                return fighters[index].fighter_id
        return None

    @staticmethod
    def _parse_fighter_summary(soup: BeautifulSoup, link: Tag, index: int) -> Fighter:
        fighter_id = _id_from_url(str(link.get("href")))
        name = _text(link) or "Unknown fighter"
        nicknames = soup.select(".b-fight-details__person-name + .b-fight-details__person-desc")
        nickname = _text(nicknames[index]) if index < len(nicknames) else None
        return Fighter(fighter_id=fighter_id, name=name, nickname=nickname, source_url=str(link.get("href")))

    def enrich_fighter(self, fighter: Fighter) -> Fighter:
        if not fighter.source_url:
            return fighter
        soup = BeautifulSoup(self.client.get_text(fighter.source_url), "html.parser")
        record = _text(soup.select_one(".b-content__title-record")) or ""
        nums = re.findall(r"\d+", record)
        fields: dict[str, str | None] = {}
        for item in soup.select(".b-list__box-list-item"):
            label = _text(item.select_one(".b-list__box-item-title"))
            if label:
                title = item.select_one(".b-list__box-item-title")
                if title:
                    title.extract()
                fields[label.rstrip(":").upper()] = _text(item)
        fighter.height_in = self._height(fields.get("HEIGHT"))
        fighter.reach_in = float(_number(fields.get("REACH"))) if _number(fields.get("REACH")) else None
        fighter.stance = fields.get("STANCE")
        fighter.dob = _date(fields.get("DOB"))
        fighter.wins = int(nums[0]) if len(nums) > 0 else None
        fighter.losses = int(nums[1]) if len(nums) > 1 else None
        fighter.draws = int(nums[2]) if len(nums) > 2 else None
        return fighter

    @staticmethod
    def _height(value: str | None) -> float | None:
        if not value:
            return None
        match = re.search(r"(\d+)\s*'\s*(\d+)", value)
        return float(int(match.group(1)) * 12 + int(match.group(2))) if match else None

    @classmethod
    def _parse_round_stats(
        cls, soup: BeautifulSoup, fight_id: str, fighters: list[Fighter]
    ) -> list[RoundStat]:
        by_key: dict[tuple[str, int], RoundStat] = {}
        for table in soup.select("table"):
            headers = [(_text(n) or "").upper().replace("%", " PCT") for n in table.select("thead th")]
            if not headers or "ROUND" not in headers[0]:
                continue
            for row in table.select("tbody tr"):
                cells = row.select("td")
                round_no = _number(_text(cells[0])) if cells else None
                if round_no is None:
                    continue
                for fighter_index, fighter in enumerate(fighters):
                    key = (fighter.fighter_id, round_no)
                    stat = by_key.setdefault(key, RoundStat(fight_id, fighter.fighter_id, round_no))
                    for header, cell in zip(headers[1:], cells[1:], strict=False):
                        values = [_text(node) for node in cell.select("p")]
                        value = values[fighter_index] if fighter_index < len(values) else _text(cell)
                        cls._assign_stat(stat, header, value)
        return sorted(by_key.values(), key=lambda s: (s.round, s.fighter_id))

    @staticmethod
    def _assign_stat(stat: RoundStat, header: str, value: str | None) -> None:
        scalar = {
            "KD": "knockdowns",
            "SUB ATT": "submissions",
            "REV.": "reversals",
            "REV": "reversals",
            "CTRL": "control_seconds",
        }
        pairs = {
            "SIG. STR.": "sig_str",
            "SIG. STR": "sig_str",
            "TOTAL STR.": "total_str",
            "TOTAL STR": "total_str",
            "TD": "takedowns",
            "HEAD": "head",
            "BODY": "body",
            "LEG": "leg",
            "DISTANCE": "distance",
            "CLINCH": "clinch",
            "GROUND": "ground",
        }
        if header == "CTRL":
            stat.control_seconds = _seconds(value)
        elif header in scalar:
            setattr(stat, scalar[header], _number(value))
        elif header in pairs:
            landed, attempted = _of(value)
            setattr(stat, f"{pairs[header]}_landed", landed)
            setattr(stat, f"{pairs[header]}_attempted", attempted)
