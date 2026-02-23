"""SQLAlchemy ORM models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # UUID as text
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

    __table_args__ = (
        Index("idx_speeches_speaker_id", "speaker_id"),
        Index("idx_speeches_speaker_name", "speaker_name"),
        Index("idx_speeches_date", "speech_date"),
        Index("idx_speeches_source", "source"),
        Index("idx_speeches_type", "speech_type"),
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
