"""SQLAlchemy ORM models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Source(Base):
    """Data source registry (FRED, BLS, Treasury, etc.)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    rate_limit_per_min: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    series: Mapped[list["Series"]] = relationship(back_populates="source")
    fetch_jobs: Mapped[list["FetchJob"]] = relationship(back_populates="source")


class Series(Base):
    """Time series metadata."""

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[str | None] = mapped_column(String(20))
    units: Mapped[str | None] = mapped_column(String(100))
    seasonal_adjustment: Mapped[str | None] = mapped_column(String(20))
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="series")
    observations: Mapped[list["Observation"]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_series_source_external", "source_id", "external_id", unique=True),)


class Observation(Base):
    """Time series data points."""

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric)
    release_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_num: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    series: Mapped["Series"] = relationship(back_populates="observations")

    __table_args__ = (
        Index("idx_observations_series_date", "series_id", "date"),
        Index("idx_observations_release", "release_date"),
        Index(
            "idx_observations_unique",
            "series_id",
            "date",
            "revision_num",
            unique=True,
        ),
    )


class FetchJob(Base):
    """Scheduled data fetch jobs."""

    __tablename__ = "fetch_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    series_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    schedule: Mapped[str | None] = mapped_column(String(50))
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    next_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="fetch_jobs")
    logs: Mapped[list["FetchLog"]] = relationship(back_populates="job")


class FetchLog(Base):
    """Audit log for fetch operations."""

    __tablename__ = "fetch_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("fetch_jobs.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(20))
    records_fetched: Mapped[int | None] = mapped_column(Integer)
    records_inserted: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Relationships
    job: Mapped["FetchJob"] = relationship(back_populates="logs")


class EconomicEvent(Base):
    """External economic events table (populated by extraction agent)."""

    __tablename__ = "economic_events"

    id: Mapped[str] = mapped_column(PGUUID(as_uuid=False), primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    calendar_date: Mapped[str | None] = mapped_column(Text)
    time_ny: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(Text)
    consensus: Mapped[str | None] = mapped_column(Text)
    last_value: Mapped[str | None] = mapped_column(Text)
    actual_result: Mapped[str | None] = mapped_column(Text)
    result_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_date: Mapped[date | None] = mapped_column(Date)
    importance_indicator: Mapped[str | None] = mapped_column(Text)
    day_date: Mapped[str | None] = mapped_column(Text)


class EconomicEventForecast(Base):
    """Source-specific economic forecast rows."""

    __tablename__ = "economic_event_forecasts"

    id: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        server_default=sql_text("gen_random_uuid()::text"),
    )
    economic_event_id: Mapped[str | None] = mapped_column(
        PGUUID(as_uuid=False),
        ForeignKey("economic_events.id")
    )
    parsed_research_id: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_date: Mapped[date | None] = mapped_column(Date)
    document_name: Mapped[str | None] = mapped_column(Text)
    document_link: Mapped[str | None] = mapped_column(Text)
    document_hash: Mapped[str | None] = mapped_column(Text)
    indicator_key: Mapped[str] = mapped_column(Text, nullable=False)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)
    period: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    forecast_type: Mapped[str] = mapped_column(Text, nullable=False)
    forecast_value_numeric: Mapped[Decimal | None] = mapped_column(Numeric)
    forecast_value_low: Mapped[Decimal | None] = mapped_column(Numeric)
    forecast_value_high: Mapped[Decimal | None] = mapped_column(Numeric)
    forecast_value_text: Mapped[str] = mapped_column(Text, nullable=False)
    forecast_unit: Mapped[str | None] = mapped_column(Text)
    qualifier_text: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=sql_text("'pending'"),
    )
    upload_source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=sql_text("'research_analysis_layer'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_economic_event_forecasts_event_id", "economic_event_id"),
        Index(
            "idx_economic_event_forecasts_indicator_release_date",
            "indicator_key",
            "release_date",
        ),
        Index(
            "idx_economic_event_forecasts_source_source_date",
            "source",
            "source_date",
        ),
        Index(
            "idx_economic_event_forecasts_sem_unique",
            "parsed_research_id",
            "indicator_key",
            "forecast_value_text",
            "release_date",
            unique=True,
        ),
    )


class Release(Base):
    """Economic data releases (from FRED)."""

    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fred_release_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    press_release: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    release_dates: Mapped[list["ReleaseDate"]] = relationship(
        back_populates="release", cascade="all, delete-orphan"
    )


class ReleaseDate(Base):
    """Scheduled release dates for economic releases."""

    __tablename__ = "release_dates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"))
    release_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    release: Mapped["Release"] = relationship(back_populates="release_dates")

    __table_args__ = (
        Index("idx_release_dates_release_id", "release_id"),
        Index("idx_release_dates_date", "release_date"),
        Index("idx_release_dates_unique", "release_id", "release_date", unique=True),
    )


class ReleaseCalendarSyncRun(Base):
    """Audit log for release calendar sync attempts."""

    __tablename__ = "release_calendar_sync_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    days_ahead: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_acquired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    releases_fetched: Mapped[int | None] = mapped_column(Integer)
    releases_expected: Mapped[int | None] = mapped_column(Integer)
    releases_inserted: Mapped[int | None] = mapped_column(Integer)
    releases_updated: Mapped[int | None] = mapped_column(Integer)
    dates_fetched: Mapped[int | None] = mapped_column(Integer)
    dates_expected: Mapped[int | None] = mapped_column(Integer)
    dates_inserted: Mapped[int | None] = mapped_column(Integer)
    dates_skipped: Mapped[int | None] = mapped_column(Integer)
    dates_skipped_missing_release: Mapped[int | None] = mapped_column(Integer)
    dates_removed: Mapped[int | None] = mapped_column(Integer)
    dates_complete: Mapped[bool | None] = mapped_column(Boolean)
    destructive_cleanup_performed: Mapped[bool | None] = mapped_column(Boolean)
    integrity_ok: Mapped[bool | None] = mapped_column(Boolean)
    degraded_reason: Mapped[str | None] = mapped_column(Text)
    missing_anchors: Mapped[list[str] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_release_calendar_sync_runs_started", "started_at"),
        Index("idx_release_calendar_sync_runs_status", "status"),
    )


class Speaker(Base):
    """Central bank officials who give speeches."""

    __tablename__ = "speakers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)  # e.g., "Chair", "Governor"
    institution: Mapped[str] = mapped_column(Text, nullable=False)  # e.g., "Federal Reserve"
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    speeches: Mapped[list["Speech"]] = relationship(back_populates="speaker")
    speaker_events: Mapped[list["SpeakerEvent"]] = relationship(
        back_populates="speaker"
    )


class Speech(Base):
    """Central bank speeches, statements, and press conferences."""

    __tablename__ = "speeches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    speaker_id: Mapped[int | None] = mapped_column(ForeignKey("speakers.id"))
    speaker_name: Mapped[str] = mapped_column(Text, nullable=False)  # Denormalized
    title: Mapped[str | None] = mapped_column(Text)
    speech_date: Mapped[date] = mapped_column(Date, nullable=False)
    speech_type: Mapped[str | None] = mapped_column(String(50))  # speech, statement, press_conference
    source: Mapped[str] = mapped_column(Text, nullable=False)  # Federal Reserve, ECB, etc.
    content_type: Mapped[str | None] = mapped_column(String(10))  # html, pdf
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int | None] = mapped_column(Integer)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    speaker: Mapped["Speaker"] = relationship(back_populates="speeches")
    speaker_events: Mapped[list["SpeakerEvent"]] = relationship(
        back_populates="speech"
    )

    __table_args__ = (
        Index("idx_speeches_speaker_id", "speaker_id"),
        Index("idx_speeches_speaker_name", "speaker_name"),
        Index("idx_speeches_date", "speech_date"),
        Index("idx_speeches_source", "source"),
        Index("idx_speeches_type", "speech_type"),
    )


class SpeakerEvent(Base):
    """Upcoming / scheduled Fed Board communications calendar events."""

    __tablename__ = "speaker_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    speaker_id: Mapped[int | None] = mapped_column(ForeignKey("speakers.id"))
    speaker_name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="Federal Reserve Board"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    speech_id: Mapped[int | None] = mapped_column(ForeignKey("speeches.id"))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    speaker: Mapped["Speaker | None"] = relationship(back_populates="speaker_events")
    speech: Mapped["Speech | None"] = relationship(back_populates="speaker_events")

    __table_args__ = (
        Index("idx_speaker_events_scheduled_start", "scheduled_start"),
        Index("idx_speaker_events_speaker_name", "speaker_name"),
        Index("idx_speaker_events_event_type", "event_type"),
        Index("idx_speaker_events_status", "status"),
        Index("idx_speaker_events_speaker_id", "speaker_id"),
        {"sqlite_autoincrement": True},
    )


class SpeakerEventSyncRun(Base):
    """Audit log for Fed speaker calendar sync attempts."""

    __tablename__ = "speaker_event_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    events_fetched: Mapped[int | None] = mapped_column(Integer)
    events_kept: Mapped[int | None] = mapped_column(Integer)
    events_inserted: Mapped[int | None] = mapped_column(Integer)
    events_updated: Mapped[int | None] = mapped_column(Integer)
    events_cancelled: Mapped[int | None] = mapped_column(Integer)
    events_skipped: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_speaker_event_sync_runs_started", "started_at"),
        Index("idx_speaker_event_sync_runs_status", "status"),
        {"sqlite_autoincrement": True},
    )


class TreasuryAuction(Base):
    """Treasury auction results."""

    __tablename__ = "treasury_auctions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cusip: Mapped[str] = mapped_column(String(9), nullable=False)
    security_type: Mapped[str] = mapped_column(String(20), nullable=False)
    security_term: Mapped[str | None] = mapped_column(String(20))
    auction_date: Mapped[date] = mapped_column(Date, nullable=False)
    issue_date: Mapped[date | None] = mapped_column(Date)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    high_yield: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    high_discount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    bid_to_cover_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    total_accepted: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    total_tendered: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    offering_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    competitive_accepted: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    noncompetitive_accepted: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    primary_dealer_accepted: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    direct_bidder_accepted: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    indirect_bidder_accepted: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    reopening: Mapped[bool] = mapped_column(default=False)
    original_cusip: Mapped[str | None] = mapped_column(String(9))
    announcement_date: Mapped[date | None] = mapped_column(Date)
    auction_format: Mapped[str | None] = mapped_column(String(30))
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_treasury_auctions_cusip", "cusip"),
        Index("idx_treasury_auctions_date", "auction_date"),
        Index("idx_treasury_auctions_type", "security_type"),
        Index("idx_treasury_auctions_cusip_date", "cusip", "auction_date", unique=True),
    )
