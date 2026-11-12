# Scrivener

Economic and markets data sourcing platform.

Scrivener collects, normalizes, and serves economic and financial market data from free public APIs (FRED, BLS, Treasury). It provides a unified interface for querying time series data and Treasury auction results.

## Features

- **Multi-source data collection**: FRED (31 series), BLS (10+ series), Treasury auctions, Fed speeches
- **Central bank communications**: Speeches, statements, press conferences, and Board speaker calendar events
- **Automated scheduling**: Daily sweeps + calendar-driven fetches for economic releases and Fed speaker events
- **Query layer**: SeriesQuery and AuctionQuery utilities for data access
- **REST API**: FastAPI service with auto-generated docs
- **CLI**: Full management interface for manual operations

## Quick Start

### Installation

```bash
# Clone and setup
cd scrivener
python3.11 -m venv venv
source venv/bin/activate
pip install -e .
```

### Configuration

Create a `.env` file:

```bash
# Database: the local Compose Postgres (see "Running in-house" below)
DATABASE_URL=postgresql://user:password@localhost:5433/sophia

# API Keys
FRED_API_KEY=your-fred-api-key
BLS_API_KEY=your-bls-api-key  # Optional

# Scheduler (defaults shown)
DEFAULT_LOOKBACK_YEARS=5
DAILY_SWEEP_HOUR=17
DAILY_SWEEP_MINUTE=0
TIMEZONE=America/New_York
```

### Initialize Database

```bash
scrivener init-db
```

### Fetch Data

```bash
# Fetch a single series
scrivener fetch fred GDP

# Fetch all core series for a source
scrivener fetch-core fred

# Run a full sweep
scrivener sweep all
```

### Query Data

```bash
# Get latest value
scrivener query FEDFUNDS --latest

# Get time series
scrivener query GDP --days 365

# Query auctions
scrivener query-auctions --summary
scrivener query-auctions --type Note --days 60
```

### Start Services

```bash
# Start the scheduler
scrivener scheduler

# Start the API server
scrivener serve --port 8000
```

Deployment notes:
- Run two long-lived processes: the scheduler (`scrivener scheduler`) and the API server (`scrivener serve`).
- Order does not matter. The scheduler keeps `release_dates` current itself (daily sync, and at start-up when it is empty); `scrivener sync-releases` is still available for a manual refresh.
- `scrivener sync-releases` now reports whether the FRED snapshot was complete. Only `complete` runs perform destructive cleanup of future `release_dates`; degraded runs stay insert-only for safety and exit non-zero.

### Running in-house

Since 2026-11-12 Scrivener runs on the local host instead of AWS and Supabase. `make up` from the repo root starts Postgres, the API (`scrivener`) and the scheduler (`scrivener-scheduler`); all restart on their own after a reboot (Docker Desktop must start at login). Both services use the Compose Postgres; `DATABASE_URL` in `infra/.env` points at the same database through `localhost:5433` for CLI use on the host. The previous Supabase URL is kept there, commented out, as a fallback. The AWS deployment files (a standalone `docker-compose.yml`, systemd units and the email-alert watchdog) were removed at the same time; git history has them.

On a fresh database the tables are created at start-up, the scheduler syncs the release calendar, and a catch-up sweep backfills the lookback window (5 years by default).

Observations are insert-only: each row is one vintage of a value, keyed on the date it became known (`realtime_start`). FRED values come from ALFRED, FRED's archive of past releases, so their history of revisions is real; BLS values have no archive and are stamped with the day Scrivener first saw them (`vintage_source = observed`). The sweep fetches only vintages newer than those stored. To load the full history of the reference series (`CPILFESL`, `DGS2`, `SOFR`), run once:

```bash
scrivener backfill-vintages
```

ALFRED accepts at most 2,000 vintage dates per request, so the command pages through long histories.

## CLI Commands

| Command | Description |
|---------|-------------|
| `init-db` | Initialize database schema |
| `fetch <source> <series>` | Fetch single series |
| `fetch-core <source>` | Fetch all core series |
| `list-series <source>` | List available core series |
| `sweep [source]` | Run immediate sweep (fred/bls/all) |
| `scheduler` | Start the scheduler daemon |
| `config` | Show current configuration |
| `query <series_id>` | Query time series data |
| `query-auctions` | Query Treasury auction data |
| `auctions` | Fetch Treasury auction data |
| `upcoming-auctions` | Show upcoming Treasury auctions |
| `releases` | List known economic release types |
| `sync-releases` | Sync FRED releases and dates |
| `list-releases` | List FRED releases |
| `upcoming-releases` | Show upcoming FRED releases |
| `upcoming` | Show upcoming economic events |
| `serve` | Start the API server |
| `seed-speakers` | Seed default Fed speakers |
| `list-speakers` | List all speakers |
| `fetch-speech <url>` | Fetch and store a speech |
| `list-speeches` | List stored speeches |
| `sync-speaker-events` | Sync Fed Board speaker calendar |
| `upcoming-speaker-events` | Show upcoming Fed speaker events |

## API Endpoints

When running `scrivener serve`, the following endpoints are available:

Set `SCRIVENER_API_KEY` to enable privileged operations. Requests to
`POST /ingestion/resolve`, `POST /ingestion/series`, `POST /releases/sync`, and
`POST /speaker-events/sync` must send the same value in the
`X-Scrivener-API-Key` header. Those endpoints fail closed when no service key
is configured.

### Series
- `GET /series` - List all series
- `GET /series/search?q=...` - Search series
- `GET /series/{id}` - Get series metadata
- `GET /series/{id}/latest` - Get latest value
- `GET /series/{id}/observations` - Get time series
- `GET /series/{id}/change` - Calculate period change
- `POST /series/batch/latest` - Get multiple latest values

### Auctions
- `GET /auctions` - Get recent auctions
- `GET /auctions/summary` - Get aggregate statistics
- `GET /auctions/cusip/{cusip}` - Get by CUSIP
- `GET /auctions/yields/{type}/{term}` - Get yield history
- `GET /auctions/latest/{type}/{term}` - Get latest for type/term

### Speakers
- `GET /speakers` - List all speakers
- `GET /speakers/{id}` - Get speaker by ID

### Speeches
- `GET /speeches` - List speeches with filters
- `GET /speeches/{id}` - Get speech with full text
- `GET /speeches/by-url` - Get speech by URL
- `GET /speeches/speaker/{name}` - Get speeches by speaker

### Speaker Events (Fed Board calendar)
- `GET /speaker-events` - List calendar events with filters
- `GET /speaker-events/upcoming` - Upcoming scheduled events
- `GET /speaker-events/{id}` - Get event by ID
- `POST /speaker-events/sync` - Sync from Board `calendar.json`

### Releases
- `GET /releases` - List FRED releases
- `GET /releases/upcoming` - Get upcoming releases
- `GET /releases/today` - Get today's releases
- `GET /releases/week` - Get this week's releases
- `GET /releases/summary` - Get release summary stats
- `GET /releases/{id}` - Get release by FRED ID
- `GET /releases/{id}/schedule` - Get release with upcoming dates
- `GET /releases/{id}/dates` - Get release dates
- `POST /releases/sync` - Sync releases from FRED and report `complete` vs `degraded` calendar status (`503` on degraded syncs)

### Health
- `GET /health` - Health check

API documentation available at `/docs` when the server is running.

## Data Sources

### FRED (31 core series)
- GDP & Growth: GDP, GDPC1, A191RL1Q225SBEA
- Inflation: CPIAUCSL, CPILFESL, PCEPI, PCEPILFE
- Employment: UNRATE, PAYEMS, ICSA, CCSA, JTSJOL
- Interest Rates: FEDFUNDS, DFEDTARU, DFEDTARL, SOFR
- Treasury Yields: Full curve (DGS1MO through DGS30)
- Markets: SP500, VIXCLS, DTWEXBGS

### BLS
- Unemployment: LNS14000000
- Employment: CES0000000001
- CPI: CUSR0000SA0, CUSR0000SA0L1E
- PPI: WPUFD4

### Treasury
- Auction results (Bills, Notes, Bonds, TIPS, FRN)
- Upcoming auctions

### Fed Speeches
- Speeches, statements, press conferences
- HTML and PDF extraction
- Default speakers: Fed Board of Governors

### Fed Speaker Calendar
- Board of Governors JSON feed: `https://www.federalreserve.gov/json/calendar.json`
- Keeps speeches, testimony, discussions, FOMC / press conferences
- Skips statistical releases (owned by the FRED release calendar)

## Scheduler

The scheduler runs these jobs:

1. **Daily Sweep** (5pm ET): Fetches all core series from all sources
2. **Release Calendar Sync** (5:50am ET): Refreshes `release_dates` from FRED, 120 days ahead
3. **Calendar Check** (6am & 6pm ET): Checks `release_dates` and schedules fetches for upcoming releases
4. **Speaker Calendar Sync** (6:05am & 6:05pm ET): Upserts Fed Board speaker events from `calendar.json`

Event-triggered fetches run 1 minute after the scheduled release time.

At start-up the scheduler also:
- syncs the release calendar if `release_dates` has nothing in the next 30 days, before its first calendar check;
- runs a catch-up sweep if the FRED and BLS daily sweeps have not both succeeded since the most recent 5pm ET slot. Every sweep re-fetches the full lookback window, so one sweep fills any gap left while the host was down.

## Project Structure

```
scrivener/
├── src/
│   ├── cli.py           # CLI commands
│   ├── config.py        # Configuration
│   ├── db/              # Database models and connection
│   ├── fetchers/        # Data source fetchers
│   ├── scheduler/       # APScheduler jobs and runner
│   ├── query/           # Query utilities
│   └── api/             # FastAPI service
├── migrations/          # SQL migrations
├── pyproject.toml
└── requirements.txt
```

## Requirements

- Python 3.11+
- PostgreSQL (the local Compose Postgres 16)
- FRED API key (free at https://fred.stlouisfed.org/docs/api/api_key.html)
- BLS API key (optional, increases rate limits)

## License

MIT
