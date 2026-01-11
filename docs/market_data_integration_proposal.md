# Market Data Integration Proposal

**Document Version:** 1.0
**Date:** 2026-01-03
**Status:** Draft - Pending Review

---

## Executive Summary

This proposal outlines the integration of high-frequency market data (CME OHLCV) into the Sophia platform. The recommended architecture uses **DuckDB as an embedded analytical query engine** with **Parquet files for storage**, initially local and migrating to **AWS S3** as the dataset grows.

This approach:
- Keeps infrastructure costs near zero during the POC phase
- Handles millions of rows efficiently for backtesting and time series analysis
- Scales seamlessly from local development to cloud production
- Integrates cleanly with the existing Scrivener/Pylon architecture

---

## Table of Contents

1. [Current State](#1-current-state)
2. [Proposed Architecture](#2-proposed-architecture)
3. [Implementation Plan](#3-implementation-plan)
4. [AWS S3 Setup](#4-aws-s3-setup)
5. [Code Specifications](#5-code-specifications)
6. [Migration Path](#6-migration-path)
7. [Cost Analysis](#7-cost-analysis)
8. [Risks & Mitigations](#8-risks--mitigations)
9. [Open Questions](#9-open-questions)

---

## 1. Current State

### 1.1 Available Data

| File | Format | Size | Description |
|------|--------|------|-------------|
| `cme_data_2025_ohlcv-1m.dbn` | Databento Binary | 526 MB | 1-minute OHLCV bars |
| `glbx-mdp3-20250102-20260101.ohlcv-1m.dbn.zst` | DBN (compressed) | 83 MB | Same data, zstd compressed |
| `symbology.json` | JSON | 789 KB | Instrument ID mappings |
| `metadata.json` | JSON | 1 KB | Query parameters |
| `condition.json` | JSON | 38 KB | Data availability by date |

**Instruments:**
- ZN.FUT (10-Year T-Note)
- ZF.FUT (5-Year T-Note)
- ZB.FUT (30-Year T-Bond)
- ZQ.FUT (Fed Funds Futures)
- UB.FUT (Ultra T-Bond)
- SR3.FUT (3-Month SOFR)

**Date Range:** 2025-01-02 to 2026-01-01 (full year)

**Estimated Row Count:** ~2.5M rows (6 instruments × 252 trading days × ~1,440 minutes)

### 1.2 Existing Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  sophia_prima   │────▶│  sophia_pylon   │────▶│    scrivener    │
│    (Agent)      │     │   (Gateway)     │     │   (Data API)    │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
                                                ┌─────────────────┐
                                                │   PostgreSQL    │
                                                │   (Supabase)    │
                                                └─────────────────┘
```

**Key Integration Points:**
- `scrivener/src/api/main.py` - FastAPI endpoints
- `scrivener/src/fetchers/base.py` - Data ingestion pattern
- `pylon/src/pylon/tools/scrivener.py` - Tool definitions for agent
- `scrivener/src/db/models.py` - SQLAlchemy models
- `scrivener/src/config.py` - Settings management

---

## 2. Proposed Architecture

### 2.1 High-Level Design

```
┌──────────────────────────────────────────────────────────────────┐
│                          Scrivener                               │
│                                                                  │
│  ┌─────────────────┐   ┌─────────────────┐   ┌────────────────┐ │
│  │   PostgreSQL    │   │     DuckDB      │   │    Parquet     │ │
│  │   (Supabase)    │◄─►│   (Embedded)    │◄─►│    Files       │ │
│  │                 │   │                 │   │                │ │
│  │ - series meta   │   │ - analytical    │   │ - OHLCV data   │ │
│  │ - symbology     │   │   queries       │   │ - partitioned  │ │
│  │ - speeches      │   │ - joins across  │   │   by symbol    │ │
│  │ - releases      │   │   data sources  │   │                │ │
│  └─────────────────┘   └─────────────────┘   └───────┬────────┘ │
│                                                      │          │
└──────────────────────────────────────────────────────┼──────────┘
                                                       │
                              ┌─────────────────────────┘
                              │
                              ▼
               ┌──────────────────────────────┐
               │      AWS S3 (Future)         │
               │  s3://sophia-market-data/    │
               │  └── ohlcv/                  │
               │      ├── ZN/                 │
               │      │   └── 2025.parquet    │
               │      ├── ZF/                 │
               │      │   └── 2025.parquet    │
               │      └── ...                 │
               └──────────────────────────────┘
```

### 2.2 Data Flow

**Ingestion (Monthly):**
```
DBN File ──▶ dbn_to_parquet.py ──▶ Parquet Files ──▶ S3 Upload (optional)
                    │
                    ▼
              PostgreSQL
           (symbology update)
```

**Query (Runtime):**
```
Agent ──▶ Pylon ──▶ Scrivener API ──▶ DuckDB ──▶ Parquet Files
                         │                           │
                         └───────── JOIN ────────────┘
                                     │
                                     ▼
                               PostgreSQL
                            (speeches, releases)
```

### 2.3 Why This Architecture

| Requirement | Solution |
|-------------|----------|
| Low cost (POC phase) | DuckDB is free; Parquet files are just files |
| Fast analytical queries | DuckDB processes columnar data at ~1GB/sec |
| Backtesting workloads | DuckDB excels at full-table scans with filters |
| Event correlation | DuckDB can attach PostgreSQL and JOIN across both |
| Growing data | Add new Parquet files; partition by symbol/year |
| Future scalability | Swap local path → S3 URI with one config change |

---

## 3. Implementation Plan

### Phase 1: Data Conversion & Local Setup

#### 3.1.1 Install Dependencies

Add to `scrivener/pyproject.toml`:
```toml
[project.dependencies]
duckdb = ">=1.0.0"
databento = ">=0.30.0"
pyarrow = ">=15.0.0"
```

#### 3.1.2 Create DBN-to-Parquet Conversion Script

**File:** `scrivener/src/tools/dbn_to_parquet.py`

Converts Databento DBN files to partitioned Parquet files:
- Read DBN using `databento` library
- Map instrument_id to a stable root symbol using Databento symbology (see Section 5.6)
- Partition output by symbol
- Store in `data/ohlcv/{symbol}/{year}.parquet`

#### 3.1.3 Create Symbology Loader

**File:** `scrivener/src/loaders/symbology.py`

Loads symbology.json into PostgreSQL for reference:
- Create `market_instruments` table
- Map Databento instrument_id → symbol → description
- Support date-range validity (instruments roll)

#### 3.1.4 Create DuckDB Query Module

**File:** `scrivener/src/query/market_data.py`

Provides query interface:
- `get_ohlcv(symbol, start, end, interval)` - Basic OHLCV retrieval
- `get_ohlcv_resampled(symbol, start, end, target_interval)` - Resample 1m to 5m, 1h, 1d
- `get_spread(symbol_a, symbol_b, start, end)` - Compute spreads
- `get_ohlcv_around_event(event_date, symbol, before_minutes, after_minutes)` - Event studies

### Phase 2: API & Tool Integration

#### 3.2.1 Create API Endpoints

**File:** `scrivener/src/api/market_data.py`

New FastAPI router with endpoints:
- `GET /market/ohlcv/{symbol}` - OHLCV data with date range
- `GET /market/ohlcv/{symbol}/resample` - Resampled data
- `GET /market/spread` - Spread between instruments
- `GET /market/event-study` - OHLCV around an event date

#### 3.2.2 Create Pylon Tools

**File:** `pylon/src/pylon/tools/market_data.py`

New tool definitions:
- `get_market_ohlcv` - Retrieve OHLCV for symbol/date range
- `get_market_spread` - Compute spread between instruments
- `analyze_curve_move` - Analyze yield curve changes
- `get_market_around_event` - Get market data around speeches/releases

#### 3.2.3 Register Tools in Pylon

Update `pylon/src/pylon/core.py` to include market data tools in the executor registry.

### Phase 3: S3 Integration

#### 3.3.1 AWS S3 Bucket Setup

See [Section 4: AWS S3 Setup](#4-aws-s3-setup) for detailed steps.

#### 3.3.2 Update Configuration

**File:** `scrivener/src/config.py`

Add settings:
```python
# Market Data Configuration
market_data_backend: Literal["local", "s3"] = "local"
market_data_local_path: str = "data/ohlcv"
market_data_s3_bucket: str = ""
market_data_s3_prefix: str = "ohlcv"
aws_region: str = "us-east-1"
```

#### 3.3.3 Update Query Module for S3

Modify `market_data.py` to construct paths based on backend:
```python
if settings.market_data_backend == "s3":
    path = f"s3://{settings.market_data_s3_bucket}/{settings.market_data_s3_prefix}/{symbol}/*.parquet"
else:
    path = f"{settings.market_data_local_path}/{symbol}/*.parquet"
```

DuckDB handles S3 paths natively with the `httpfs` extension.

### Phase 4: Testing & Documentation

#### 3.4.1 Unit Tests

- Test DBN conversion accuracy
- Test DuckDB queries return correct results
- Test S3 fallback behavior

#### 3.4.2 Integration Tests

- Test full flow: Agent → Pylon → Scrivener → DuckDB → Response
- Test cross-source joins (market data + speeches)

#### 3.4.3 Documentation

- Update runbook.md with market data operations
- Add example queries for common use cases

---

## 4. AWS S3 Setup

### 4.1 Prerequisites

- AWS account with appropriate permissions
- AWS CLI installed and configured (`aws configure`)
- IAM user or role with S3 permissions

### 4.2 Create S3 Bucket

```bash
# Set variables
BUCKET_NAME="sophia-market-data-$(aws sts get-caller-identity --query Account --output text)"
REGION="us-east-1"

# Create bucket
aws s3api create-bucket \
    --bucket $BUCKET_NAME \
    --region $REGION

# Enable versioning (recommended for data integrity)
aws s3api put-bucket-versioning \
    --bucket $BUCKET_NAME \
    --versioning-configuration Status=Enabled

# Block public access (security best practice)
aws s3api put-public-access-block \
    --bucket $BUCKET_NAME \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Add lifecycle rule to transition old versions to Glacier after 90 days
aws s3api put-bucket-lifecycle-configuration \
    --bucket $BUCKET_NAME \
    --lifecycle-configuration '{
        "Rules": [
            {
                "ID": "ArchiveOldVersions",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "NoncurrentVersionTransitions": [
                    {
                        "NoncurrentDays": 90,
                        "StorageClass": "GLACIER"
                    }
                ]
            }
        ]
    }'
```

### 4.3 Create IAM Policy

Create a policy file `sophia-market-data-policy.json`:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ListBucket",
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:GetBucketLocation"
            ],
            "Resource": "arn:aws:s3:::sophia-market-data-*"
        },
        {
            "Sid": "ReadWriteObjects",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject"
            ],
            "Resource": "arn:aws:s3:::sophia-market-data-*/*"
        }
    ]
}
```

Apply the policy:

```bash
# Create the policy
aws iam create-policy \
    --policy-name SophiaMarketDataAccess \
    --policy-document file://sophia-market-data-policy.json

# Attach to your IAM user or role
aws iam attach-user-policy \
    --user-name <YOUR_IAM_USER> \
    --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/SophiaMarketDataAccess
```

### 4.4 Configure DuckDB for S3 Access

DuckDB requires the `httpfs` extension and AWS credentials:

```python
import duckdb

conn = duckdb.connect()

# Install and load httpfs extension
conn.execute("INSTALL httpfs")
conn.execute("LOAD httpfs")

# Configure S3 credentials (uses environment variables or IAM role)
conn.execute(f"""
    SET s3_region = '{settings.aws_region}';
    SET s3_access_key_id = '{settings.aws_access_key_id}';
    SET s3_secret_access_key = '{settings.aws_secret_access_key}';
""")

# Or use IAM role (recommended for EC2/ECS deployment)
conn.execute("SET s3_use_credential_chain = true;")
```

### 4.5 Upload Initial Data

```bash
# After converting DBN to Parquet locally
aws s3 sync data/ohlcv/ s3://$BUCKET_NAME/ohlcv/ \
    --storage-class STANDARD_IA

# Verify upload
aws s3 ls s3://$BUCKET_NAME/ohlcv/ --recursive --human-readable
```

### 4.6 Environment Variables

Add to `.env` or deployment configuration:

```bash
# Market Data Configuration
MARKET_DATA_BACKEND=s3  # or "local" for development
MARKET_DATA_LOCAL_PATH=data/ohlcv
MARKET_DATA_S3_BUCKET=sophia-market-data-123456789012
MARKET_DATA_S3_PREFIX=ohlcv
AWS_REGION=us-east-1

# AWS Credentials (if not using IAM role)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

---

## 5. Code Specifications

### 5.1 Database Models

**File:** `scrivener/src/db/models.py`

```python
class MarketInstrument(Base):
    """Market instrument metadata from Databento symbology."""
    __tablename__ = "market_instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    databento_instrument_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_symbol: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g., "ZN.FUT"
    description: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str] = mapped_column(String(20), default="CME")
    asset_class: Mapped[str] = mapped_column(String(20), default="futures")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_market_instruments_symbol", "symbol"),
        Index("idx_market_instruments_parent", "parent_symbol"),
        Index("idx_market_instruments_databento_id", "databento_instrument_id"),
        Index("idx_market_instruments_valid_range", "valid_from", "valid_to"),
    )
```

### 5.2 Configuration

**File:** `scrivener/src/config.py`

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Market Data Configuration
    market_data_backend: Literal["local", "s3"] = "local"
    market_data_local_path: str = "data/ohlcv"
    market_data_s3_bucket: str = ""
    market_data_s3_prefix: str = "ohlcv"

    # AWS Configuration
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_use_credential_chain: bool = True  # Use IAM role if available

    @computed_field
    @property
    def market_data_base_path(self) -> str:
        """Get the base path for market data (local or S3)."""
        if self.market_data_backend == "s3":
            return f"s3://{self.market_data_s3_bucket}/{self.market_data_s3_prefix}"
        return self.market_data_local_path
```

#### 5.2.1 Timezone Policy

Scrivener uses `settings.timezone` (currently `America/New_York`) for scheduling. Market data should align to the same canonical timezone to avoid event-study drift and DST boundary issues.

Policy:
- Store OHLCV timestamps as timezone-aware and normalized to `settings.timezone`.
- Require API inputs to be timezone-aware ISO timestamps, or interpret naive inputs as `settings.timezone`.
- If data sources are UTC (typical for Databento), convert to `settings.timezone` during ingestion and preserve tz info in Parquet.

Example conversion (ingest and query):
```python
from zoneinfo import ZoneInfo

settings = get_settings()
tz = ZoneInfo(settings.timezone)

# Ingest: convert from UTC to configured timezone, keep tz-aware
df["ts"] = df["ts"].dt.tz_convert(tz)

# Query: treat naive timestamps as configured timezone
event_time = event_time.replace(tzinfo=tz) if event_time.tzinfo is None else event_time.astimezone(tz)
```

### 5.3 DuckDB Query Module

**File:** `scrivener/src/query/market_data.py`

```python
"""Market data query module using DuckDB."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import duckdb
from pydantic import BaseModel

from scrivener.src.config import get_settings


class OHLCVBar(BaseModel):
    """Single OHLCV bar."""
    timestamp: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class MarketDataQuery:
    """Query interface for market data stored in Parquet files."""

    _conn: duckdb.DuckDBPyConnection | None = None

    @classmethod
    def _get_connection(cls) -> duckdb.DuckDBPyConnection:
        """Get or create DuckDB connection with S3 support."""
        if cls._conn is None:
            settings = get_settings()
            cls._conn = duckdb.connect(":memory:")

            # Install and load extensions
            cls._conn.execute("INSTALL httpfs")
            cls._conn.execute("LOAD httpfs")

            # Configure S3 if needed
            if settings.market_data_backend == "s3":
                if settings.aws_use_credential_chain:
                    cls._conn.execute("SET s3_use_credential_chain = true")
                else:
                    cls._conn.execute(f"SET s3_region = '{settings.aws_region}'")
                    cls._conn.execute(f"SET s3_access_key_id = '{settings.aws_access_key_id}'")
                    cls._conn.execute(f"SET s3_secret_access_key = '{settings.aws_secret_access_key}'")

        return cls._conn

    @classmethod
    def _get_parquet_path(cls, symbol: str, year: int | None = None) -> str:
        """Construct path to Parquet file(s)."""
        settings = get_settings()
        base = settings.market_data_base_path
        if year:
            return f"{base}/{symbol}/{year}.parquet"
        return f"{base}/{symbol}/*.parquet"

    @classmethod
    def get_ohlcv(
        cls,
        symbol: str,
        start_date: date,
        end_date: date,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get OHLCV bars for a symbol within a date range.

        Args:
            symbol: Instrument symbol (e.g., "ZN", "ZF")
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            limit: Maximum number of bars to return

        Returns:
            List of OHLCV bar dictionaries
        """
        conn = cls._get_connection()
        path = cls._get_parquet_path(symbol)

        query = f"""
            SELECT
                ts as timestamp,
                symbol,
                open,
                high,
                low,
                close,
                volume
            FROM read_parquet('{path}')
            WHERE ts >= '{start_date}'::DATE
              AND ts < '{end_date}'::DATE + INTERVAL '1 day'
            ORDER BY ts
        """

        if limit:
            query += f" LIMIT {limit}"

        result = conn.execute(query).fetchall()
        columns = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
        return [dict(zip(columns, row)) for row in result]

    @classmethod
    def get_ohlcv_resampled(
        cls,
        symbol: str,
        start_date: date,
        end_date: date,
        interval: str = "1h",
    ) -> list[dict[str, Any]]:
        """
        Get OHLCV bars resampled to a larger interval.

        Args:
            symbol: Instrument symbol
            start_date: Start date
            end_date: End date
            interval: Target interval ('5m', '15m', '1h', '4h', '1d')

        Returns:
            List of resampled OHLCV bars
        """
        conn = cls._get_connection()
        path = cls._get_parquet_path(symbol)

        interval_map = {
            "5m": "5 minutes",
            "15m": "15 minutes",
            "1h": "1 hour",
            "4h": "4 hours",
            "1d": "1 day",
        }

        duckdb_interval = interval_map.get(interval, "1 hour")

        query = f"""
            SELECT
                time_bucket(INTERVAL '{duckdb_interval}', ts) as timestamp,
                '{symbol}' as symbol,
                FIRST(open) as open,
                MAX(high) as high,
                MIN(low) as low,
                LAST(close) as close,
                SUM(volume) as volume
            FROM read_parquet('{path}')
            WHERE ts >= '{start_date}'::DATE
              AND ts < '{end_date}'::DATE + INTERVAL '1 day'
            GROUP BY 1
            ORDER BY 1
        """

        result = conn.execute(query).fetchall()
        columns = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
        return [dict(zip(columns, row)) for row in result]

    @classmethod
    def get_spread(
        cls,
        symbol_a: str,
        symbol_b: str,
        start_date: date,
        end_date: date,
        interval: str = "1d",
    ) -> list[dict[str, Any]]:
        """
        Compute spread between two instruments (A - B).

        Args:
            symbol_a: First symbol (long leg)
            symbol_b: Second symbol (short leg)
            start_date: Start date
            end_date: End date
            interval: Aggregation interval

        Returns:
            List of spread values over time
        """
        conn = cls._get_connection()
        path_a = cls._get_parquet_path(symbol_a)
        path_b = cls._get_parquet_path(symbol_b)

        interval_map = {"1h": "1 hour", "4h": "4 hours", "1d": "1 day"}
        duckdb_interval = interval_map.get(interval, "1 day")

        query = f"""
            WITH a AS (
                SELECT
                    time_bucket(INTERVAL '{duckdb_interval}', ts) as bucket,
                    LAST(close) as close_a
                FROM read_parquet('{path_a}')
                WHERE ts >= '{start_date}'::DATE
                  AND ts < '{end_date}'::DATE + INTERVAL '1 day'
                GROUP BY 1
            ),
            b AS (
                SELECT
                    time_bucket(INTERVAL '{duckdb_interval}', ts) as bucket,
                    LAST(close) as close_b
                FROM read_parquet('{path_b}')
                WHERE ts >= '{start_date}'::DATE
                  AND ts < '{end_date}'::DATE + INTERVAL '1 day'
                GROUP BY 1
            )
            SELECT
                a.bucket as timestamp,
                '{symbol_a}' as symbol_a,
                '{symbol_b}' as symbol_b,
                a.close_a,
                b.close_b,
                (a.close_a - b.close_b) as spread
            FROM a
            JOIN b ON a.bucket = b.bucket
            ORDER BY a.bucket
        """

        result = conn.execute(query).fetchall()
        columns = ["timestamp", "symbol_a", "symbol_b", "close_a", "close_b", "spread"]
        return [dict(zip(columns, row)) for row in result]

    @classmethod
    def get_ohlcv_around_event(
        cls,
        symbol: str,
        event_timestamp: datetime,
        minutes_before: int = 60,
        minutes_after: int = 60,
    ) -> list[dict[str, Any]]:
        """
        Get OHLCV bars around a specific event (e.g., Fed speech).

        Args:
            symbol: Instrument symbol
            event_timestamp: The event timestamp
            minutes_before: Minutes of data before event
            minutes_after: Minutes of data after event

        Returns:
            List of OHLCV bars with relative time indicator
        """
        conn = cls._get_connection()
        path = cls._get_parquet_path(symbol)

        query = f"""
            SELECT
                ts as timestamp,
                symbol,
                open,
                high,
                low,
                close,
                volume,
                EXTRACT(EPOCH FROM (ts - '{event_timestamp}'::TIMESTAMP)) / 60 as minutes_from_event
            FROM read_parquet('{path}')
            WHERE ts >= '{event_timestamp}'::TIMESTAMP - INTERVAL '{minutes_before} minutes'
              AND ts <= '{event_timestamp}'::TIMESTAMP + INTERVAL '{minutes_after} minutes'
            ORDER BY ts
        """

        result = conn.execute(query).fetchall()
        columns = ["timestamp", "symbol", "open", "high", "low", "close", "volume", "minutes_from_event"]
        return [dict(zip(columns, row)) for row in result]

    @classmethod
    def get_curve_steepening(
        cls,
        long_symbol: str,
        short_symbol: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """
        Analyze curve steepening/flattening between two points.

        Args:
            long_symbol: Long-dated instrument (e.g., ZB for 30y)
            short_symbol: Short-dated instrument (e.g., ZN for 10y)
            start_date: Start date
            end_date: End date

        Returns:
            Summary of curve movement with start/end spread and change
        """
        conn = cls._get_connection()
        path_long = cls._get_parquet_path(long_symbol)
        path_short = cls._get_parquet_path(short_symbol)

        query = f"""
            WITH long_prices AS (
                SELECT
                    ts::DATE as day,
                    LAST(close) as close
                FROM read_parquet('{path_long}')
                WHERE ts >= '{start_date}'::DATE
                  AND ts < '{end_date}'::DATE + INTERVAL '1 day'
                GROUP BY 1
            ),
            short_prices AS (
                SELECT
                    ts::DATE as day,
                    LAST(close) as close
                FROM read_parquet('{path_short}')
                WHERE ts >= '{start_date}'::DATE
                  AND ts < '{end_date}'::DATE + INTERVAL '1 day'
                GROUP BY 1
            ),
            spreads AS (
                SELECT
                    l.day,
                    (l.close - s.close) as spread
                FROM long_prices l
                JOIN short_prices s ON l.day = s.day
            )
            SELECT
                MIN(day) as start_date,
                MAX(day) as end_date,
                FIRST(spread) as start_spread,
                LAST(spread) as end_spread,
                LAST(spread) - FIRST(spread) as spread_change,
                CASE
                    WHEN LAST(spread) > FIRST(spread) THEN 'steepened'
                    WHEN LAST(spread) < FIRST(spread) THEN 'flattened'
                    ELSE 'unchanged'
                END as direction
            FROM spreads
        """

        result = conn.execute(query).fetchone()
        if result:
            return {
                "long_symbol": long_symbol,
                "short_symbol": short_symbol,
                "start_date": result[0],
                "end_date": result[1],
                "start_spread": result[2],
                "end_spread": result[3],
                "spread_change": result[4],
                "direction": result[5],
            }
        return {}
```

### 5.4 API Endpoints

**File:** `scrivener/src/api/market_data.py`

```python
"""Market data API endpoints."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from scrivener.src.query.market_data import MarketDataQuery


router = APIRouter(prefix="/market", tags=["market"])


class OHLCVResponse(BaseModel):
    """OHLCV bar response model."""
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class SpreadResponse(BaseModel):
    """Spread response model."""
    timestamp: datetime
    symbol_a: str
    symbol_b: str
    close_a: float
    close_b: float
    spread: float


class CurveAnalysisResponse(BaseModel):
    """Curve steepening analysis response."""
    long_symbol: str
    short_symbol: str
    start_date: date
    end_date: date
    start_spread: float
    end_spread: float
    spread_change: float
    direction: str


@router.get("/ohlcv/{symbol}", response_model=list[OHLCVResponse])
def get_ohlcv(
    symbol: str,
    start_date: Annotated[date, Query(description="Start date (YYYY-MM-DD)")],
    end_date: Annotated[date, Query(description="End date (YYYY-MM-DD)")],
    limit: Annotated[int | None, Query(le=100000)] = None,
):
    """Get OHLCV bars for a symbol within a date range."""
    try:
        result = MarketDataQuery.get_ohlcv(symbol, start_date, end_date, limit)
        if not result:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ohlcv/{symbol}/resample", response_model=list[OHLCVResponse])
def get_ohlcv_resampled(
    symbol: str,
    start_date: Annotated[date, Query(description="Start date (YYYY-MM-DD)")],
    end_date: Annotated[date, Query(description="End date (YYYY-MM-DD)")],
    interval: Annotated[str, Query(description="Target interval: 5m, 15m, 1h, 4h, 1d")] = "1h",
):
    """Get OHLCV bars resampled to a larger interval."""
    valid_intervals = {"5m", "15m", "1h", "4h", "1d"}
    if interval not in valid_intervals:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interval. Must be one of: {valid_intervals}"
        )

    try:
        result = MarketDataQuery.get_ohlcv_resampled(symbol, start_date, end_date, interval)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spread", response_model=list[SpreadResponse])
def get_spread(
    symbol_a: Annotated[str, Query(description="Long leg symbol (e.g., ZB)")],
    symbol_b: Annotated[str, Query(description="Short leg symbol (e.g., ZN)")],
    start_date: Annotated[date, Query(description="Start date (YYYY-MM-DD)")],
    end_date: Annotated[date, Query(description="End date (YYYY-MM-DD)")],
    interval: Annotated[str, Query(description="Aggregation interval: 1h, 4h, 1d")] = "1d",
):
    """Compute spread between two instruments over time."""
    try:
        result = MarketDataQuery.get_spread(symbol_a, symbol_b, start_date, end_date, interval)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/curve-analysis", response_model=CurveAnalysisResponse)
def get_curve_analysis(
    long_symbol: Annotated[str, Query(description="Long-dated symbol (e.g., ZB for 30y)")],
    short_symbol: Annotated[str, Query(description="Short-dated symbol (e.g., ZN for 10y)")],
    start_date: Annotated[date, Query(description="Start date (YYYY-MM-DD)")],
    end_date: Annotated[date, Query(description="End date (YYYY-MM-DD)")],
):
    """Analyze curve steepening/flattening between two tenors."""
    try:
        result = MarketDataQuery.get_curve_steepening(
            long_symbol, short_symbol, start_date, end_date
        )
        if not result:
            raise HTTPException(status_code=404, detail="No data found for analysis")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/event-study/{symbol}", response_model=list[OHLCVResponse])
def get_event_study(
    symbol: str,
    event_time: Annotated[datetime, Query(description="Event timestamp (ISO format)")],
    minutes_before: Annotated[int, Query(ge=1, le=480)] = 60,
    minutes_after: Annotated[int, Query(ge=1, le=480)] = 60,
):
    """Get OHLCV bars around a specific event timestamp."""
    try:
        result = MarketDataQuery.get_ohlcv_around_event(
            symbol, event_time, minutes_before, minutes_after
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 5.5 Pylon Tool Definitions

**File:** `pylon/src/pylon/tools/market_data.py`

```python
"""Market data tool definitions for Pylon."""

import json
from typing import Any

from pylon.tools.base import (
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)
from pylon.clients.scrivener import ScrivenerClient


MARKET_DATA_TOOLS = [
    ToolDefinition(
        name="get_market_ohlcv",
        description=(
            "Get OHLCV (Open, High, Low, Close, Volume) price bars for a CME futures instrument. "
            "Available instruments: ZN (10Y Note), ZF (5Y Note), ZB (30Y Bond), ZQ (Fed Funds), "
            "UB (Ultra Bond), SR3 (SOFR). Data is 1-minute bars from 2025."
        ),
        parameters=[
            ToolParameter(
                name="symbol",
                type=ToolParameterType.STRING,
                description="Instrument symbol: ZN, ZF, ZB, ZQ, UB, or SR3",
                required=True,
            ),
            ToolParameter(
                name="start_date",
                type=ToolParameterType.STRING,
                description="Start date in YYYY-MM-DD format",
                required=True,
            ),
            ToolParameter(
                name="end_date",
                type=ToolParameterType.STRING,
                description="End date in YYYY-MM-DD format",
                required=True,
            ),
            ToolParameter(
                name="interval",
                type=ToolParameterType.STRING,
                description="Resample interval: 1m (raw), 5m, 15m, 1h, 4h, 1d. Default: 1h",
                required=False,
                default="1h",
            ),
        ],
    ),
    ToolDefinition(
        name="get_market_spread",
        description=(
            "Calculate the price spread between two instruments over time. "
            "Useful for analyzing curve trades (e.g., ZB-ZN for 30s10s spread). "
            "Returns daily spread values."
        ),
        parameters=[
            ToolParameter(
                name="symbol_a",
                type=ToolParameterType.STRING,
                description="Long leg symbol (e.g., ZB for long 30-year)",
                required=True,
            ),
            ToolParameter(
                name="symbol_b",
                type=ToolParameterType.STRING,
                description="Short leg symbol (e.g., ZN for short 10-year)",
                required=True,
            ),
            ToolParameter(
                name="start_date",
                type=ToolParameterType.STRING,
                description="Start date in YYYY-MM-DD format",
                required=True,
            ),
            ToolParameter(
                name="end_date",
                type=ToolParameterType.STRING,
                description="End date in YYYY-MM-DD format",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="analyze_curve_move",
        description=(
            "Analyze how the yield curve has steepened or flattened between two dates. "
            "Compares long-dated vs short-dated instruments and reports the change. "
            "Example: Has the 30s10s curve steepened since Powell's last speech?"
        ),
        parameters=[
            ToolParameter(
                name="long_symbol",
                type=ToolParameterType.STRING,
                description="Long-dated instrument (ZB for 30y, ZN for 10y, ZF for 5y)",
                required=True,
            ),
            ToolParameter(
                name="short_symbol",
                type=ToolParameterType.STRING,
                description="Short-dated instrument (ZN for 10y, ZF for 5y)",
                required=True,
            ),
            ToolParameter(
                name="start_date",
                type=ToolParameterType.STRING,
                description="Start date in YYYY-MM-DD format",
                required=True,
            ),
            ToolParameter(
                name="end_date",
                type=ToolParameterType.STRING,
                description="End date in YYYY-MM-DD format",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="get_market_around_event",
        description=(
            "Get market data around a specific event (Fed speech, economic release, etc.). "
            "Returns minute-by-minute data before and after the event timestamp. "
            "Useful for event studies and market reaction analysis."
        ),
        parameters=[
            ToolParameter(
                name="symbol",
                type=ToolParameterType.STRING,
                description="Instrument symbol",
                required=True,
            ),
            ToolParameter(
                name="event_time",
                type=ToolParameterType.STRING,
                description="Event timestamp in ISO format (e.g., 2025-03-19T14:00:00)",
                required=True,
            ),
            ToolParameter(
                name="minutes_before",
                type=ToolParameterType.INTEGER,
                description="Minutes of data before the event (default: 60, max: 480)",
                required=False,
                default=60,
            ),
            ToolParameter(
                name="minutes_after",
                type=ToolParameterType.INTEGER,
                description="Minutes of data after the event (default: 60, max: 480)",
                required=False,
                default=60,
            ),
        ],
    ),
]


class MarketDataToolExecutor:
    """Executes market data tools against Scrivener."""

    def __init__(self, client: ScrivenerClient) -> None:
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        """Get all market data tool definitions."""
        return MARKET_DATA_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any]) -> ToolResult:
        """Execute a market data tool."""
        try:
            match tool_name:
                case "get_market_ohlcv":
                    interval = parameters.get("interval", "1h")
                    if interval == "1m":
                        data = await self.client.get_market_ohlcv(
                            parameters["symbol"],
                            parameters["start_date"],
                            parameters["end_date"],
                        )
                    else:
                        data = await self.client.get_market_ohlcv_resampled(
                            parameters["symbol"],
                            parameters["start_date"],
                            parameters["end_date"],
                            interval,
                        )

                case "get_market_spread":
                    data = await self.client.get_market_spread(
                        parameters["symbol_a"],
                        parameters["symbol_b"],
                        parameters["start_date"],
                        parameters["end_date"],
                    )

                case "analyze_curve_move":
                    data = await self.client.get_curve_analysis(
                        parameters["long_symbol"],
                        parameters["short_symbol"],
                        parameters["start_date"],
                        parameters["end_date"],
                    )

                case "get_market_around_event":
                    data = await self.client.get_event_study(
                        parameters["symbol"],
                        parameters["event_time"],
                        parameters.get("minutes_before", 60),
                        parameters.get("minutes_after", 60),
                    )

                case _:
                    return ToolResult.fail(f"Unknown tool: {tool_name}")

            return ToolResult.ok(json.dumps(data, indent=2, default=str))

        except Exception as e:
            return ToolResult.fail(str(e))
```

### 5.6 DBN to Parquet Conversion Script

**Symbology mapping strategy (required)**

The keys in `symbology.json` are not guaranteed to be simple contract symbols (examples include `SR3:CF H8U8H9U9`, `UD:ZN: TL 2685399`, and `ZQX6-ZQF8`). A reliable mapping must use Databento-provided symbology fields rather than string slicing or heuristics.

Recommended approach:
- Use Databento symbology outputs that include a stable root/parent for each `instrument_id` (for example, a `parent` or `root` stype in the export).
- If a root field is not available in the export, build a vetted allowlist mapping for supported roots (`ZN`, `ZF`, `ZB`, `ZQ`, `UB`, `SR3`) from Databento’s official symbology docs and store it alongside the ingest job.
- Fail fast if any `instrument_id` cannot be mapped to a known root symbol; do not silently drop or guess.

Concrete mapping flow (example):
1. Export symbology with an explicit root/parent field (preferred) or a stype that can be normalized to a root.
2. Build a `instrument_id -> root_symbol` mapping table from that export.
3. Validate that every mapped root is in an allowlist `{ZN, ZF, ZB, ZQ, UB, SR3}`.
4. If any `instrument_id` is missing a root or maps outside the allowlist, raise an error and halt ingestion.
5. Persist the mapping used for the ingest run for auditability.

Pre-ingest validation:
- Run `services/scrivener/src/tools/validate_symbology.py` against `metadata.json` and `symbology.json` to flag ambiguous keys before conversion.

Fallback mapping when only `symbology.json` keys are available (strict, allowlist-based):
```python
import re

ALLOWED_ROOTS = ("SR3", "UB", "ZB", "ZN", "ZF", "ZQ")

def infer_root_from_key(symbology_key: str) -> str:
    tokens = re.findall(r"[A-Z0-9]+", symbology_key)
    roots = {root for token in tokens for root in ALLOWED_ROOTS if token.startswith(root)}
    if len(roots) != 1:
        raise ValueError(f"Ambiguous or missing root in symbology key: {symbology_key}")
    return next(iter(roots))
```

**File:** `scrivener/src/tools/dbn_to_parquet.py`

```python
#!/usr/bin/env python3
"""Convert Databento DBN files to partitioned Parquet files."""

import json
import logging
import re
from pathlib import Path

import databento as db
import pyarrow as pa
import pyarrow.parquet as pq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_metadata(metadata_path: Path) -> set[str]:
    """
    Load allowed parent symbols from Databento metadata.json.

    Returns:
        Set of root symbols (e.g., {"ZN", "ZF", "ZB", "ZQ", "UB", "SR3"})
    """
    with open(metadata_path) as f:
        data = json.load(f)

    symbols = data.get("query", {}).get("symbols", [])
    roots = {symbol.split(".")[0] for symbol in symbols}
    if not roots:
        raise ValueError("No symbols found in metadata.json")
    return roots


def infer_root_from_key(symbology_key: str, allowed_roots: set[str]) -> str:
    """Infer a unique root from a symbology key using a strict allowlist."""
    tokens = re.findall(r"[A-Z0-9]+", symbology_key)
    roots = {root for token in tokens for root in allowed_roots if token.startswith(root)}
    if len(roots) != 1:
        raise ValueError(f"Ambiguous or missing root in symbology key: {symbology_key}")
    return next(iter(roots))


def load_symbology(symbology_path: Path, allowed_roots: set[str]) -> dict[int, str]:
    """
    Load symbology mapping from Databento symbology.json.

    Returns:
        Dict mapping instrument_id (int) to symbol (str)
    """
    with open(symbology_path) as f:
        data = json.load(f)

    # Build reverse mapping: instrument_id -> parent symbol
    id_to_symbol = {}
    for symbol, mappings in data.get("result", {}).items():
        for mapping in mappings:
            instrument_id = int(mapping["s"])
            parent = infer_root_from_key(symbol, allowed_roots)
            id_to_symbol[instrument_id] = parent

    return id_to_symbol


def convert_dbn_to_parquet(
    dbn_path: Path,
    metadata_path: Path,
    symbology_path: Path,
    output_dir: Path,
    partition_by: str = "symbol",
) -> dict[str, int]:
    """
    Convert a DBN file to partitioned Parquet files.

    Args:
        dbn_path: Path to the .dbn file
        symbology_path: Path to symbology.json
        output_dir: Output directory for Parquet files
        partition_by: Partition strategy ('symbol' or 'date')

    Returns:
        Dict with counts per symbol
    """
    logger.info(f"Loading metadata from {metadata_path}")
    allowed_roots = load_metadata(metadata_path)

    logger.info(f"Loading symbology from {symbology_path}")
    id_to_symbol = load_symbology(symbology_path, allowed_roots)

    logger.info(f"Reading DBN file: {dbn_path}")
    store = db.DBNStore.from_file(str(dbn_path))

    # Convert to DataFrame
    df = store.to_df()
    logger.info(f"Loaded {len(df)} rows")

    # Map instrument_id to symbol
    df["symbol"] = df["instrument_id"].map(id_to_symbol)

    # Drop rows with unmapped symbols
    unmapped = df["symbol"].isna().sum()
    if unmapped > 0:
        raise ValueError(f"Unmapped instrument_id count: {unmapped}")

    # Rename columns to standard OHLCV
    df = df.rename(columns={
        "ts_event": "ts",
    })

    # Select and order columns
    columns = ["ts", "symbol", "open", "high", "low", "close", "volume"]
    df = df[columns]

    # Convert to appropriate types
    # Align with Scrivener's configured timezone (see services/scrivener/src/config.py).
    df["ts"] = df["ts"].dt.tz_convert("America/New_York")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Partition by symbol and write
    counts = {}
    for symbol in df["symbol"].unique():
        symbol_df = df[df["symbol"] == symbol]
        symbol_dir = output_dir / symbol
        symbol_dir.mkdir(exist_ok=True)

        # Get year from data
        year = symbol_df["ts"].dt.year.iloc[0]
        output_path = symbol_dir / f"{year}.parquet"

        # Write Parquet with compression
        table = pa.Table.from_pandas(symbol_df, preserve_index=False)
        pq.write_table(
            table,
            output_path,
            compression="snappy",
            row_group_size=100_000,
        )

        counts[symbol] = len(symbol_df)
        logger.info(f"Wrote {len(symbol_df)} rows to {output_path}")

    return counts


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Convert DBN to Parquet")
    parser.add_argument("dbn_path", type=Path, help="Path to DBN file")
    parser.add_argument("--metadata", type=Path, required=True, help="Path to metadata.json")
    parser.add_argument("--symbology", type=Path, required=True, help="Path to symbology.json")
    parser.add_argument("--output", type=Path, default=Path("data/ohlcv"), help="Output directory")

    args = parser.parse_args()

    counts = convert_dbn_to_parquet(args.dbn_path, args.metadata, args.symbology, args.output)

    print("\nConversion complete:")
    for symbol, count in sorted(counts.items()):
        print(f"  {symbol}: {count:,} rows")
    print(f"  Total: {sum(counts.values()):,} rows")


if __name__ == "__main__":
    main()
```

---

## 6. Migration Path

### 6.1 Phase 1 → Phase 2: Local to S3

When local storage becomes insufficient:

1. **Upload existing Parquet files to S3:**
   ```bash
   aws s3 sync data/ohlcv/ s3://$BUCKET_NAME/ohlcv/
   ```

2. **Update environment variables:**
   ```bash
   MARKET_DATA_BACKEND=s3
   MARKET_DATA_S3_BUCKET=sophia-market-data-...
   ```

3. **Restart Scrivener** - queries automatically use S3 paths

4. **Optional: Remove local files** to free disk space

### 6.2 Adding New Data (Monthly Process)

```bash
# 1. Download new DBN file from Databento
# 2. Convert to Parquet
python -m scrivener.src.tools.dbn_to_parquet \
    new_data.dbn \
    --symbology symbology.json \
    --output data/ohlcv

# 3. Upload to S3 (if using S3 backend)
aws s3 sync data/ohlcv/ s3://$BUCKET_NAME/ohlcv/

# 4. Verify
python -c "from scrivener.src.query.market_data import MarketDataQuery; print(MarketDataQuery.get_ohlcv('ZN', '2026-01-01', '2026-01-31')[:5])"
```

---

## 7. Cost Analysis

### 7.1 Phase 1: Local Development (Current)

| Item | Cost |
|------|------|
| DuckDB | Free (open source) |
| Parquet files | Free (local storage) |
| PostgreSQL (Supabase) | Existing plan |
| **Total** | **$0/month additional** |

### 7.2 Phase 2: S3 Production

| Item | Estimate | Notes |
|------|----------|-------|
| S3 Storage (Standard-IA) | ~$1.50/month | 500MB × $0.0125/GB × 12 months growth |
| S3 Requests | ~$0.50/month | GET requests for queries |
| Data Transfer | ~$0/month | Same-region access from EC2 |
| **Total** | **~$2-5/month** | Scales with data volume |

### 7.3 Cost Comparison: Alternatives

| Approach | Estimated Monthly Cost |
|----------|------------------------|
| **DuckDB + S3 (Recommended)** | $2-5 |
| PostgreSQL (expanded rows) | $25+ (Supabase Pro for row limits) |
| TimescaleDB Cloud | $30+ |
| AWS Athena | $5-20 (per-query pricing adds up) |
| Dedicated time-series DB | $50+ |

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| DuckDB memory pressure on large queries | Medium | Medium | Use LIMIT clauses; add query timeout; consider external mode for very large datasets |
| S3 latency for interactive queries | Low | Low | DuckDB caches; most queries scan <100MB; use local mode for development |
| Databento schema changes | Low | Medium | Version symbology.json; validate on ingest |
| Parquet corruption | Low | High | S3 versioning enabled; keep source DBN files |
| Concurrency issues with in-memory DuckDB | Medium | Medium | Avoid sharing a single DuckDB connection across threads; use per-request or per-worker connections |

### 8.1 Multi-worker DuckDB Connection Model

Assume multiple concurrent requests. DuckDB connections are not thread-safe, so a single cached connection will break under multi-worker FastAPI.

Recommended patterns:
- **Per-request connection:** open/close a DuckDB connection inside each request handler.
- **Per-worker connection:** initialize one connection per process (worker) and reuse it in that process only.
- **Pool:** maintain a small pool with strict check-out per request; no shared connections across threads.

---

## 9. Open Questions

1. **Backfill requirements**: How much historical data beyond 2025 is needed? This affects storage sizing.

2. **Real-time data**: Is there a future need for streaming/real-time market data? This proposal covers historical only.

3. **Additional instruments**: Beyond Treasury futures, what other CME products are planned? (ES, NQ, CL, GC, etc.)

4. **Cross-source joins**: How frequently will queries need to join market data with speeches/releases? This affects whether to pre-compute event alignments.

5. **Access patterns**: Will multiple users/agents query simultaneously? May need to consider DuckDB connection pooling.

---

## Appendix A: File Structure After Implementation

```
sophia/
├── data/
│   └── ohlcv/                          # Local Parquet storage
│       ├── ZN/
│       │   └── 2025.parquet
│       ├── ZF/
│       │   └── 2025.parquet
│       ├── ZB/
│       │   └── 2025.parquet
│       ├── ZQ/
│       │   └── 2025.parquet
│       ├── UB/
│       │   └── 2025.parquet
│       └── SR3/
│           └── 2025.parquet
├── services/
│   ├── scrivener/
│   │   └── src/
│   │       ├── api/
│   │       │   ├── main.py             # Add market router
│   │       │   └── market_data.py      # NEW: Market data endpoints
│   │       ├── db/
│   │       │   └── models.py           # Add MarketInstrument model
│   │       ├── query/
│   │       │   └── market_data.py      # NEW: DuckDB query module
│   │       ├── loaders/
│   │       │   └── symbology.py        # NEW: Symbology loader
│   │       ├── tools/
│   │       │   └── dbn_to_parquet.py   # NEW: Conversion script
│   │       └── config.py               # Add market data settings
│   └── sophia_pylon/
│       └── src/
│           └── pylon/
│               ├── tools/
│               │   └── market_data.py  # NEW: Market data tools
│               ├── clients/
│               │   └── scrivener.py    # Add market data methods
│               └── core.py             # Register market tools
└── docs/
    └── market_data_integration_proposal.md  # This document
```

---

## Appendix B: Example Agent Interactions

### Query 1: Basic Price History

**User:** "What was the ZN price on March 15, 2025?"

**Agent uses:** `get_market_ohlcv(symbol="ZN", start_date="2025-03-15", end_date="2025-03-15", interval="1d")`

### Query 2: Curve Analysis

**User:** "How has the curve steepened since Powell's last speech?"

**Agent uses:**
1. `search_speeches(query="Powell")` → Gets latest Powell speech date
2. `analyze_curve_move(long_symbol="ZB", short_symbol="ZN", start_date=<speech_date>, end_date="2026-01-03")`

### Query 3: Event Study

**User:** "Show me how ZN traded around the December FOMC meeting"

**Agent uses:**
1. `get_releases(source="FRED")` → Finds FOMC meeting date/time
2. `get_market_around_event(symbol="ZN", event_time="2025-12-18T14:00:00", minutes_before=60, minutes_after=120)`

### Query 4: Backtesting Support

**User:** "Give me daily closes for ZN and ZF for all of 2025 for backtesting"

**Agent uses:**
1. `get_market_ohlcv(symbol="ZN", start_date="2025-01-01", end_date="2025-12-31", interval="1d")`
2. `get_market_ohlcv(symbol="ZF", start_date="2025-01-01", end_date="2025-12-31", interval="1d")`

---

*End of Proposal*
