from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .agent import UFCCollectorAgent
from .config import Settings
from .storage import Database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ufc-collector", description="Collect UFC data and build point-in-time model features."
    )
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect", help="Run the incremental collector")
    collect.add_argument("--full", action="store_true", help="Re-fetch historical event pages")
    collect.add_argument("--no-enrich", action="store_true", help="Skip fighter profile requests")
    collect.add_argument("--forever", action="store_true", help="Repeat on UFC_REFRESH_SECONDS")
    export = subparsers.add_parser("export", help="Export normalized or model-ready data")
    export.add_argument("--format", choices=("features", "jsonl"), default="features")
    export.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    if args.command == "collect":
        agent = UFCCollectorAgent(settings)
        if args.forever:
            agent.run_forever(full=args.full, enrich_fighters=not args.no_enrich)
        else:
            result = agent.run_once(full=args.full, enrich_fighters=not args.no_enrich)
            logging.info("Collected %d events and %d fights", result.events, result.fights)
        return 0
    database = Database(settings.db_path)
    try:
        count = (
            database.export_features(args.output)
            if args.format == "features"
            else database.write_jsonl(args.output)
        )
        logging.info("Exported %d rows to %s", count, args.output)
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
