# UFC Data Collector Agent

A production-minded Python agent that incrementally collects public UFC fight data, normalizes it
into SQLite, and exports **point-in-time** features suitable for prediction models. The first source
adapter targets UFCStats because it provides event, bout, fighter, and round-level statistics without
requiring private credentials.

## What it collects

| Entity | Fields |
| --- | --- |
| Events | name, date, location, completed/upcoming status, source URL |
| Bouts | corners, winner, division, method/detail, finish round/time, format, referee, order |
| Fighters | name, nickname, height, reach, stance, DOB, record |
| Every round/fighter | knockdowns, significant/total strikes landed and attempted, takedowns, submissions, reversals, control time |
| Strike breakdown | head/body/leg and distance/clinch/ground landed and attempted |
| Provenance | stable source identifiers/URLs, collection run status and timestamps |

The collector is idempotent, uses upserts, retries transient failures, rate-limits requests, keeps
partial progress, and revisits recent events so corrected results and upcoming cards are refreshed.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env  # export these variables or load them with your process manager
export UFC_USER_AGENT='My-UFC-Research/1.0 (contact: me@example.com)'

# Historical backfill (this intentionally takes time because requests are throttled)
ufc-collector collect --full

# Fast incremental refresh, suitable for cron
ufc-collector collect

# Or run as a long-lived agent (default refresh: every six hours)
ufc-collector collect --forever

# Leakage-safe, one-row-per-fight model input
ufc-collector export --format features --output data/model_features.csv

# Normalized bout records for downstream processing
ufc-collector export --format jsonl --output data/fights.jsonl
```

Environment variables are documented in [`.env.example`](.env.example). The program deliberately
does not silently load `.env`; use your deployment platform, `set -a; source .env; set +a`, or a
secrets manager.

## Prediction safety

The feature export joins each target fight only to fights whose **event date is earlier** than the
target. It therefore avoids the common mistake of leaking the target result or later career totals
into training rows. It emits:

- prior fight/win/loss counts per corner;
- cumulative significant strikes landed/attempted;
- cumulative takedowns landed/attempted;
- cumulative control time; and
- the red-corner win label (empty for draws/no contests/unresolved bouts).

Split train/validation/test sets chronologically, not randomly. Fighter identity, event date, division,
and raw cumulative values are retained so a modeling pipeline can add rates, recency weighting, Elo,
opponent strength, rest days, age, reach differential, and uncertainty handling.

## Data not available from UFCStats

No honest collector can guarantee “all data.” For stronger predictions, add licensed/authorized source
adapters for weigh-in results, betting line movement, judging scorecards, short-notice replacements,
injuries, training camps, travel/altitude, drug-test sanctions, regional fight history, and live data.
Do not fabricate missing values or scrape sources whose terms prohibit it. Keep source-specific raw
payloads and timestamps so corrections can be audited.

UFCStats markup can change. Parsers are isolated in `sources/ufcstats.py`, and fixture-based tests make
breakages visible. Before operating at scale, review the site's current terms and robots policy, set a
real contact address in the user agent, retain the default delay (or increase it), and stop collection
if asked by the site operator. This project is not affiliated with UFC.

## Storage model

SQLite tables are created automatically:

- `events`, `fighters`, `fights`, `round_stats`: normalized model-ready facts;
- `collection_runs`: observability for successful and failed runs; and
- `raw_pages`: reserved provenance storage for adapters that retain permitted raw responses.

SQLite is ideal for a single collector. For concurrent workers, port the same keys and upsert semantics
to PostgreSQL. Run one process per database to avoid duplicate network work.

## Development

```bash
pip install -e '.[dev]'
pytest
ruff check .
```

Tests use local HTML fixtures and never hit UFCStats.

