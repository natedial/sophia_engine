# Scrivener: Economic & Markets Data Platform

## Overview

Scrivener is a data sourcing and management platform that collects, normalizes, and serves economic and financial market data. It serves as the foundational data layer for downstream tools and agents.

---

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| FRED Fetcher | Complete | 31 core series, 5-year lookback, release calendar |
| BLS Fetcher | Complete | Batch fetching, employment/inflation data |
| Treasury Fetcher | Complete | Auction data from Fiscal Data API |
| Fed Speech Fetcher | Complete | Speeches, statements, press conferences |
| Database | Complete | PostgreSQL on Supabase with RLS |
| Scheduler | Complete | APScheduler with daily sweep + calendar-driven fetches |
| Query Layer | Complete | SeriesQuery and AuctionQuery utilities |
| API Layer | Complete | FastAPI service with full CRUD |
| CLI | Complete | Full management interface |

---

## Tech Stack

### Core Components

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Data Collection** | Python 3.11+ | Rich ecosystem (pandas, requests, httpx), best library support for FRED/BLS APIs |
| **Data Pipeline** | Go (future) | High-performance processing when scale demands it |
| **Database** | PostgreSQL (Supabase) | Managed, user-friendly, built-in REST API, good free tier |
| **Task Scheduling** | APScheduler | Python-native, handles cron-like jobs for data fetches |
| **Caching** | Redis (optional) | For hot data paths when latency matters |
| **API Layer** | FastAPI | Async, auto-docs, excellent performance for Python |

### Python Dependencies

```
httpx>=0.27.0          # Async HTTP client
pandas>=2.2.0          # Data manipulation
sqlalchemy>=2.0.0      # ORM / raw SQL
psycopg2-binary>=2.9.0 # PostgreSQL driver
pydantic>=2.0.0        # Data validation
pydantic-settings>=2.0.0
fredapi>=0.5.0         # Official FRED API wrapper
apscheduler>=3.10.0    # Job scheduling
python-dotenv>=1.0.0   # Environment management
typer>=0.12.0          # CLI framework
rich>=13.0.0           # Rich terminal output
fastapi>=0.115.0       # API framework
uvicorn>=0.32.0        # ASGI server
beautifulsoup4>=4.12.0 # HTML parsing (speeches)
pypdf2>=3.0.0          # PDF text extraction
```

---

## Data Sources

### Implemented

| Source | Data | Status | Notes |
|--------|------|--------|-------|
| **FRED** | Macro indicators, rates, GDP, inflation, yields | Complete | 31 core series |
| **BLS** | Employment, CPI, PPI, wages | Complete | 10+ core series |
| **Treasury** | Auction results, upcoming auctions | Complete | All security types |
| **Fed Speeches** | Speeches, statements, press conferences | Complete | HTML & PDF extraction |

### FRED Core Series

| Category | Series |
|----------|--------|
| GDP & Growth | GDP, GDPC1, A191RL1Q225SBEA |
| Inflation | CPIAUCSL, CPILFESL, PCEPI, PCEPILFE |
| Employment | UNRATE, PAYEMS, ICSA, CCSA, JTSJOL |
| Interest Rates | FEDFUNDS, DFEDTARU, DFEDTARL, SOFR |
| Treasury Yields | DGS1MO, DGS3MO, DGS6MO, DGS1, DGS2, DGS5, DGS7, DGS10, DGS20, DGS30 |
| Yield Spreads | T10Y2Y, T10Y3M |
| Markets | SP500, VIXCLS, DTWEXBGS |

### BLS Core Series

| Category | Series |
|----------|--------|
| Unemployment | LNS14000000 (headline rate) |
| Employment | CES0000000001 (nonfarm payrolls) |
| CPI | CUSR0000SA0 (all items), CUSR0000SA0L1E (core) |
| PPI | WPUFD4 (final demand) |

### Future Sources

| Source | Data | Notes |
|--------|------|-------|
| SEC EDGAR | Corporate filings | 10 req/sec |
| Census Bureau | Economic indicators, trade data | api.census.gov |
| DOL | Unemployment claims, OEWS | developer.dol.gov |
| World Bank | International macro | api.worldbank.org |

---

## Database Schema

### Tables

```sql
-- Data sources registry
sources (id, name, base_url, rate_limit_per_min, created_at)

-- Series metadata
series (id, source_id, external_id, name, description, frequency, units,
        seasonal_adjustment, last_updated, metadata, created_at)

-- Time series observations
observations (id, series_id, date, value, release_date, revision_num, created_at)

-- Data fetch job tracking
fetch_jobs (id, source_id, series_ids, schedule, last_run, last_status, next_run, config)

-- Audit log
fetch_logs (id, job_id, started_at, completed_at, status, records_fetched, records_inserted, error_message)

-- Treasury auction data
treasury_auctions (id, cusip, security_type, security_term, auction_date, issue_date,
                   maturity_date, high_yield, high_discount_rate, bid_to_cover_ratio,
                   offering_amount, total_accepted, total_tendered, primary_dealer_accepted,
                   direct_bidder_accepted, indirect_bidder_accepted, reopening, created_at, updated_at)

-- Central bank speakers
speakers (id, name, title, institution, is_active, created_at, updated_at)

-- Central bank speeches/statements
speeches (id, url, speaker_id, speaker_name, title, speech_date, speech_type, source,
          content_type, raw_text, word_count, scraped_at, created_at, updated_at)

-- FRED economic releases
releases (id, fred_release_id, name, link, notes, press_release, created_at, updated_at)

-- FRED release dates
release_dates (id, release_id, release_date, created_at)

-- External table (managed separately)
economic_events (id, event_name, scheduled_time, country, actual_value, forecast_value, ...)
```

### Indexes

- `idx_observations_series_date` - Fast time-range queries
- `idx_observations_release` - Release date lookups
- `idx_treasury_auctions_date` - Auction date queries
- `idx_treasury_auctions_type_term` - Type/term filtering

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        SCRIVENER                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   FRED       │  │   BLS        │  │  Treasury    │          │
│  │   Fetcher    │  │   Fetcher    │  │  Fetcher     │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                   │
│         └─────────────────┼─────────────────┘                   │
│                           ▼                                     │
│                  ┌─────────────────┐                            │
│                  │  Base Fetcher   │  ← Upserts, validation     │
│                  │  + Normalizer   │                            │
│                  └────────┬────────┘                            │
│                           │                                     │
│                           ▼                                     │
│                  ┌─────────────────┐                            │
│                  │   PostgreSQL    │  ← Supabase (session pool) │
│                  │                 │                            │
│                  └────────┬────────┘                            │
│                           │                                     │
│         ┌─────────────────┼─────────────────┐                   │
│         │                 │                 │                   │
│         ▼                 ▼                 ▼                   │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐              │
│  │  FastAPI   │   │   Query    │   │    CLI     │              │
│  │  Service   │   │   Layer    │   │  (typer)   │              │
│  └────────────┘   └────────────┘   └────────────┘              │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                       SCHEDULER                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  APScheduler                                              │  │
│  │  • Daily sweep: 5pm ET (all sources)                      │  │
│  │  • Calendar check: 6am & 6pm ET (14-hour lookahead)       │  │
│  │  • Event-triggered: 1 min after release time              │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Other Tools /  │
                    │     Agents      │
                    └─────────────────┘
```

---

## Project Phases

### Phase 1: Foundation - COMPLETE

- [x] Set up project structure
- [x] Configure Supabase project + connection
- [x] Implement database schema
- [x] Build FRED fetcher (highest value, most comprehensive)
- [x] Create base fetcher class with common logic
- [x] Basic CLI for manual data pulls
- [x] Logging and error handling

### Phase 2: Expand Sources - COMPLETE

- [x] BLS API integration (batch fetching)
- [x] Treasury data integration (Fiscal Data API)
- [x] APScheduler for automated fetches
- [x] Economic calendar integration (reads from `economic_events` table)
- [x] Event-to-series mapping (regex-based)

### Phase 3: API Layer - COMPLETE

- [x] FastAPI service with key endpoints
- [x] Query interface: by series, date range, latest
- [x] Batch queries (multiple series at once)
- [x] Auction data endpoints (recent, summary, by CUSIP, yield history)
- [x] Health check endpoint
- [ ] Authentication for external access (not needed - service-to-service)
- [ ] Rate limiting (not needed - internal service)

### Phase 4: Real-time & Reliability - PARTIAL

- [x] Economic release calendar monitoring (via `economic_events` table)
- [x] Calendar-driven fetch scheduling
- [ ] Redis caching for hot paths
- [ ] Alerting on fetch failures
- [ ] Data freshness monitoring
- [ ] Revision tracking and alerts

### Phase 5: High-Performance Pipeline (Future)

- [ ] Identify bottlenecks requiring Go rewrite
- [ ] Implement Go data pipeline components
- [ ] Benchmark and optimize

---

## Directory Structure

```
scrivener/
├── src/
│   ├── __init__.py
│   ├── cli.py                # CLI commands (typer)
│   ├── config.py             # Configuration management (pydantic-settings)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py     # Database connection handling
│   │   └── models.py         # SQLAlchemy models
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── base.py           # Base fetcher class
│   │   ├── fred.py           # FRED API fetcher
│   │   ├── bls.py            # BLS API fetcher
│   │   └── treasury.py       # Treasury Fiscal Data API fetcher
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── scheduler.py      # APScheduler setup
│   │   ├── jobs.py           # Scheduled job definitions
│   │   ├── calendar.py       # Economic events calendar integration
│   │   └── runner.py         # Main scheduler runner
│   ├── query/
│   │   ├── __init__.py
│   │   ├── series.py         # SeriesQuery utilities
│   │   └── auctions.py       # AuctionQuery utilities
│   └── api/
│       ├── __init__.py
│       └── main.py           # FastAPI app
├── migrations/
│   └── 001_initial_schema.sql
├── tests/
├── .env.example
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `scrivener init-db` | Initialize database schema |
| `scrivener fetch <source> <series>` | Fetch single series |
| `scrivener fetch-core <source>` | Fetch all core series for source |
| `scrivener list-series <source>` | List available core series |
| `scrivener sweep [source]` | Run immediate sweep (fred/bls/all) |
| `scrivener scheduler` | Start the scheduler daemon |
| `scrivener config` | Show current configuration |
| `scrivener query <series_id>` | Query time series data |
| `scrivener query-auctions` | Query Treasury auction data |
| `scrivener auctions` | Fetch Treasury auction data |
| `scrivener upcoming-auctions` | Show upcoming Treasury auctions |
| `scrivener releases` | List known economic release types |
| `scrivener upcoming` | Show upcoming economic events |
| `scrivener sync-releases` | Sync FRED releases and dates |
| `scrivener list-releases` | List FRED releases |
| `scrivener upcoming-releases` | Show upcoming FRED releases |
| `scrivener serve` | Start the API server |
| `scrivener seed-speakers` | Seed default Fed speakers |
| `scrivener list-speakers` | List all speakers |
| `scrivener fetch-speech <url>` | Fetch and store a speech |
| `scrivener list-speeches` | List stored speeches |

---

## API Endpoints

### Series

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/series` | GET | List all series |
| `/series/search` | GET | Search series by name |
| `/series/{id}` | GET | Get series metadata |
| `/series/{id}/latest` | GET | Get latest value |
| `/series/{id}/observations` | GET | Get time series data |
| `/series/{id}/change` | GET | Calculate period change |
| `/series/batch/latest` | POST | Get multiple latest values |

### Auctions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auctions` | GET | Get recent auctions |
| `/auctions/summary` | GET | Get aggregate statistics |
| `/auctions/cusip/{cusip}` | GET | Get by CUSIP |
| `/auctions/yields/{type}/{term}` | GET | Get yield history |
| `/auctions/latest/{type}/{term}` | GET | Get latest for type/term |

### Speakers

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/speakers` | GET | List all speakers |
| `/speakers/{id}` | GET | Get speaker by ID |

### Speeches

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/speeches` | GET | List speeches with filters |
| `/speeches/{id}` | GET | Get speech with full text |
| `/speeches/by-url` | GET | Get speech by URL |
| `/speeches/speaker/{name}` | GET | Get speeches by speaker |

### Releases

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/releases` | GET | List FRED releases |
| `/releases/upcoming` | GET | Get upcoming releases |
| `/releases/{id}` | GET | Get release by FRED ID |
| `/releases/{id}/dates` | GET | Get release dates |
| `/releases/sync` | POST | Sync releases from FRED |

### Health

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |

---

## Scheduler Configuration

| Job | Schedule | Description |
|-----|----------|-------------|
| Daily Sweep | 5pm ET | Fetch all core series from all sources |
| Calendar Check | 6am & 6pm ET | Check economic_events table, schedule fetches |
| Event Fetch | Release time + 1 min | Triggered by calendar for known releases |

### Event-to-Series Mapping

The scheduler maps economic event names to data series using regex patterns:

| Event Pattern | Release Type | FRED Series | BLS Series |
|---------------|--------------|-------------|------------|
| CPI / Consumer Price Index | CPI | CPIAUCSL, CPILFESL | CUSR0000SA0, CUSR0000SA0L1E |
| Nonfarm Payrolls / Employment | NFP | PAYEMS, UNRATE | CES0000000001, LNS14000000 |
| GDP | GDP | GDP, GDPC1 | - |
| JOLTS | JOLTS | JTSJOL | JTS000000000000000JOL |
| PCE | PCE | PCEPI, PCEPILFE | - |
| Initial Claims | CLAIMS | ICSA, CCSA | - |

---

## Configuration

Environment variables (`.env`):

```bash
# Database (Supabase session pooler)
DATABASE_URL=postgresql://postgres.xxx:password@aws-0-us-east-1.pooler.supabase.com:5432/postgres

# Alternative individual settings
SUPABASE_DB_HOST=aws-0-us-east-1.pooler.supabase.com
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres.xxx
SUPABASE_DB_PASSWORD=your-password

# API Keys
FRED_API_KEY=your-fred-api-key
BLS_API_KEY=your-bls-api-key  # Optional, increases rate limits

# Scheduler
DEFAULT_LOOKBACK_YEARS=5
DAILY_SWEEP_HOUR=17
DAILY_SWEEP_MINUTE=0
TIMEZONE=America/New_York
```

---

## Decisions Made

| Decision | Choice | Notes |
|----------|--------|-------|
| Historical depth | 5 years initial | Schema supports fetching further back |
| Update frequency | Daily sweep at 5pm ET + calendar-driven | Calendar checks at 6am/6pm ET |
| Market data | Delayed feeds acceptable | Real-time not required |
| Supabase region | AWS us-east-1 | Aligns with other infrastructure |
| Connection type | Session pooler | Not direct connection (DNS issues) |
| Calendar source | `economic_events` table | External table, regex mapping to series |
| API auth | None | Service-to-service only, internal use |

---

## Next Steps / Future Work

1. **Redis caching** - Add caching layer for frequently accessed series
2. **Alerting** - Notify on fetch failures or stale data
3. **Data freshness dashboard** - Monitor last update times
4. **Revision tracking** - Track and alert on economic data revisions
5. **Additional sources** - SEC EDGAR, Census Bureau, DOL
6. **Go pipeline** - High-performance processing for scale
