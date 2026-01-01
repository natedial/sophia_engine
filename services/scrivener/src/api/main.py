"""FastAPI service for Scrivener data queries."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel

from src.query import SeriesQuery, AuctionQuery

app = FastAPI(
    title="Scrivener API",
    description="Economic and markets data query service",
    version="0.1.0",
)


# --- Response Models ---

class SeriesInfo(BaseModel):
    id: int
    external_id: str
    name: str
    description: str | None
    frequency: str | None
    units: str | None
    source: str | None
    last_updated: str | None


class Observation(BaseModel):
    date: str
    value: float | None


class LatestValue(BaseModel):
    series_id: str
    date: str
    value: float | None


class SeriesChange(BaseModel):
    series_id: str
    current_date: str
    current_value: float
    previous_date: str
    previous_value: float
    change: float
    change_type: str


class AuctionRecord(BaseModel):
    cusip: str
    security_type: str
    security_term: str | None
    auction_date: str
    issue_date: str | None
    maturity_date: str | None
    high_yield: float | None
    high_discount_rate: float | None
    bid_to_cover_ratio: float | None
    offering_amount: float | None
    total_accepted: float | None
    total_tendered: float | None
    primary_dealer_accepted: float | None
    direct_bidder_accepted: float | None
    indirect_bidder_accepted: float | None
    reopening: bool


class AuctionSummary(BaseModel):
    count: int
    period_days: int | None = None
    total_offered_millions: float | None = None
    avg_yield: float | None = None
    min_yield: float | None = None
    max_yield: float | None = None
    avg_bid_to_cover: float | None = None
    by_type: dict[str, int] | None = None


# --- Health Check ---

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


# --- Series Endpoints ---

@app.get("/series", response_model=list[dict])
def list_series(
    source: Annotated[str | None, Query(description="Filter by source (FRED, BLS)")] = None,
):
    """List all available series."""
    return SeriesQuery.list_series(source=source)


@app.get("/series/search", response_model=list[dict])
def search_series(
    q: Annotated[str, Query(description="Search term")],
    source: Annotated[str | None, Query(description="Filter by source")] = None,
    limit: Annotated[int, Query(le=100)] = 20,
):
    """Search for series by name or description."""
    return SeriesQuery.search_series(query=q, source=source, limit=limit)


@app.get("/series/{series_id}", response_model=SeriesInfo)
def get_series_info(series_id: str, source: str | None = None):
    """Get metadata for a series."""
    result = SeriesQuery.get_series_info(series_id, source=source)
    if not result:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found")
    return result


@app.get("/series/{series_id}/latest", response_model=LatestValue)
def get_latest_value(series_id: str, source: str | None = None):
    """Get the most recent value for a series."""
    result = SeriesQuery.get_latest(series_id, source=source)
    if not result:
        raise HTTPException(status_code=404, detail=f"No data found for series '{series_id}'")
    return result


@app.get("/series/{series_id}/observations", response_model=list[Observation])
def get_observations(
    series_id: str,
    start_date: Annotated[date | None, Query(description="Start date (YYYY-MM-DD)")] = None,
    end_date: Annotated[date | None, Query(description="End date (YYYY-MM-DD)")] = None,
    source: str | None = None,
    limit: Annotated[int | None, Query(le=10000)] = None,
):
    """Get observations for a series within a date range."""
    result = SeriesQuery.get_observations(
        series_id,
        start_date=start_date,
        end_date=end_date,
        source=source,
        limit=limit,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"No observations found for series '{series_id}'")
    return result


@app.get("/series/{series_id}/change", response_model=SeriesChange)
def get_series_change(
    series_id: str,
    periods: Annotated[int, Query(ge=1, le=100)] = 1,
    pct: Annotated[bool, Query(description="Return percentage change")] = True,
):
    """Calculate change from N periods ago."""
    result = SeriesQuery.get_change(series_id, periods=periods, pct=pct)
    if not result:
        raise HTTPException(status_code=404, detail=f"Insufficient data for series '{series_id}'")
    return result


@app.post("/series/batch/latest", response_model=dict[str, LatestValue | None])
def get_multiple_latest(series_ids: list[str]):
    """Get latest values for multiple series."""
    return SeriesQuery.get_multiple_latest(series_ids)


# --- Auction Endpoints ---

@app.get("/auctions", response_model=list[AuctionRecord])
def get_recent_auctions(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    security_type: Annotated[str | None, Query(description="Bill, Note, Bond, TIPS, FRN")] = None,
    limit: Annotated[int | None, Query(le=1000)] = None,
):
    """Get recent Treasury auction results."""
    return AuctionQuery.get_recent(days=days, security_type=security_type, limit=limit)


@app.get("/auctions/summary", response_model=AuctionSummary)
def get_auction_summary(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    security_type: Annotated[str | None, Query()] = None,
):
    """Get summary statistics for recent auctions."""
    return AuctionQuery.get_summary_stats(security_type=security_type, days=days)


@app.get("/auctions/cusip/{cusip}", response_model=list[AuctionRecord])
def get_auctions_by_cusip(cusip: str):
    """Get auction history for a specific CUSIP."""
    result = AuctionQuery.get_by_cusip(cusip)
    if not result:
        raise HTTPException(status_code=404, detail=f"No auctions found for CUSIP '{cusip}'")
    return result


@app.get("/auctions/yields/{security_type}/{term}", response_model=list[dict])
def get_yield_history(
    security_type: str,
    term: str,
    days: Annotated[int, Query(ge=1, le=3650)] = 365,
):
    """Get yield history for a security type/term (e.g., Note/10-Year)."""
    return AuctionQuery.get_yield_history(security_type, term, days=days)


@app.get("/auctions/latest/{security_type}/{term}", response_model=AuctionRecord)
def get_latest_auction_by_term(security_type: str, term: str):
    """Get the most recent auction for a security type/term."""
    result = AuctionQuery.get_latest_by_term(security_type, term)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No auction found for {security_type} {term}",
        )
    return result


# --- Speaker & Speech Response Models ---

class SpeakerRecord(BaseModel):
    id: int
    name: str
    title: str | None
    institution: str
    is_active: bool


class SpeechRecord(BaseModel):
    id: int
    url: str
    speaker_name: str
    title: str | None
    speech_date: str
    speech_type: str | None
    source: str
    word_count: int | None


class SpeechDetail(SpeechRecord):
    raw_text: str
    content_type: str | None
    scraped_at: str | None


# --- Speaker Endpoints ---

@app.get("/speakers", response_model=list[SpeakerRecord])
def list_speakers(
    institution: Annotated[str | None, Query(description="Filter by institution")] = None,
    active_only: Annotated[bool, Query()] = True,
):
    """List all speakers."""
    from src.db import get_session
    from src.db.models import Speaker

    with get_session() as session:
        query = session.query(Speaker)

        if institution:
            query = query.filter(Speaker.institution.ilike(f"%{institution}%"))
        if active_only:
            query = query.filter(Speaker.is_active == True)

        speakers = query.order_by(Speaker.name).all()

        return [
            SpeakerRecord(
                id=s.id,
                name=s.name,
                title=s.title,
                institution=s.institution,
                is_active=s.is_active,
            )
            for s in speakers
        ]


@app.get("/speakers/{speaker_id}", response_model=SpeakerRecord)
def get_speaker(speaker_id: int):
    """Get a speaker by ID."""
    from src.db import get_session
    from src.db.models import Speaker

    with get_session() as session:
        speaker = session.query(Speaker).filter(Speaker.id == speaker_id).first()
        if not speaker:
            raise HTTPException(status_code=404, detail=f"Speaker {speaker_id} not found")

        return SpeakerRecord(
            id=speaker.id,
            name=speaker.name,
            title=speaker.title,
            institution=speaker.institution,
            is_active=speaker.is_active,
        )


# --- Speech Endpoints ---

@app.get("/speeches", response_model=list[SpeechRecord])
def list_speeches(
    speaker: Annotated[str | None, Query(description="Filter by speaker name")] = None,
    source: Annotated[str | None, Query(description="Filter by source institution")] = None,
    speech_type: Annotated[str | None, Query(description="Filter by type")] = None,
    days: Annotated[int, Query(ge=1, le=3650)] = 90,
    limit: Annotated[int, Query(le=1000)] = 100,
):
    """List speeches with optional filters."""
    from datetime import timedelta
    from src.db import get_session
    from src.db.models import Speech

    cutoff = date.today() - timedelta(days=days)

    with get_session() as session:
        query = session.query(Speech).filter(Speech.speech_date >= cutoff)

        if speaker:
            query = query.filter(Speech.speaker_name.ilike(f"%{speaker}%"))
        if source:
            query = query.filter(Speech.source.ilike(f"%{source}%"))
        if speech_type:
            query = query.filter(Speech.speech_type == speech_type)

        speeches = query.order_by(Speech.speech_date.desc()).limit(limit).all()

        return [
            SpeechRecord(
                id=s.id,
                url=s.url,
                speaker_name=s.speaker_name,
                title=s.title,
                speech_date=s.speech_date.isoformat(),
                speech_type=s.speech_type,
                source=s.source,
                word_count=s.word_count,
            )
            for s in speeches
        ]


@app.get("/speeches/{speech_id}", response_model=SpeechDetail)
def get_speech(speech_id: int):
    """Get a speech by ID, including full text."""
    from src.db import get_session
    from src.db.models import Speech

    with get_session() as session:
        speech = session.query(Speech).filter(Speech.id == speech_id).first()
        if not speech:
            raise HTTPException(status_code=404, detail=f"Speech {speech_id} not found")

        return SpeechDetail(
            id=speech.id,
            url=speech.url,
            speaker_name=speech.speaker_name,
            title=speech.title,
            speech_date=speech.speech_date.isoformat(),
            speech_type=speech.speech_type,
            source=speech.source,
            word_count=speech.word_count,
            raw_text=speech.raw_text,
            content_type=speech.content_type,
            scraped_at=speech.scraped_at.isoformat() if speech.scraped_at else None,
        )


@app.get("/speeches/by-url", response_model=SpeechDetail)
def get_speech_by_url(url: Annotated[str, Query(description="Speech URL")]):
    """Get a speech by its URL."""
    from src.db import get_session
    from src.db.models import Speech

    with get_session() as session:
        speech = session.query(Speech).filter(Speech.url == url).first()
        if not speech:
            raise HTTPException(status_code=404, detail=f"Speech not found for URL")

        return SpeechDetail(
            id=speech.id,
            url=speech.url,
            speaker_name=speech.speaker_name,
            title=speech.title,
            speech_date=speech.speech_date.isoformat(),
            speech_type=speech.speech_type,
            source=speech.source,
            word_count=speech.word_count,
            raw_text=speech.raw_text,
            content_type=speech.content_type,
            scraped_at=speech.scraped_at.isoformat() if speech.scraped_at else None,
        )


@app.get("/speeches/speaker/{speaker_name}", response_model=list[SpeechRecord])
def get_speeches_by_speaker(
    speaker_name: str,
    limit: Annotated[int, Query(le=100)] = 20,
):
    """Get speeches by a specific speaker."""
    from src.db import get_session
    from src.db.models import Speech

    with get_session() as session:
        speeches = (
            session.query(Speech)
            .filter(Speech.speaker_name.ilike(f"%{speaker_name}%"))
            .order_by(Speech.speech_date.desc())
            .limit(limit)
            .all()
        )

        if not speeches:
            raise HTTPException(
                status_code=404,
                detail=f"No speeches found for speaker '{speaker_name}'",
            )

        return [
            SpeechRecord(
                id=s.id,
                url=s.url,
                speaker_name=s.speaker_name,
                title=s.title,
                speech_date=s.speech_date.isoformat(),
                speech_type=s.speech_type,
                source=s.source,
                word_count=s.word_count,
            )
            for s in speeches
        ]


# --- Release Response Models ---

class ReleaseRecord(BaseModel):
    id: int
    fred_release_id: int
    name: str
    link: str | None
    press_release: bool


class ReleaseDateRecord(BaseModel):
    fred_release_id: int
    name: str
    release_date: str
    link: str | None
    press_release: bool


class ReleaseSyncResult(BaseModel):
    releases: dict[str, int]
    dates: dict[str, int]


# --- Release Endpoints ---

@app.get("/releases", response_model=list[ReleaseRecord])
def list_releases(
    search: Annotated[str | None, Query(description="Search by name")] = None,
    limit: Annotated[int, Query(le=500)] = 100,
):
    """List FRED releases."""
    from src.query import ReleaseQuery

    if search:
        results = ReleaseQuery.search(search, limit=limit)
    else:
        from src.db import get_session
        from src.db.models import Release

        with get_session() as session:
            releases = session.query(Release).order_by(Release.name).limit(limit).all()
            results = [
                {
                    "fred_release_id": r.fred_release_id,
                    "name": r.name,
                    "link": r.link,
                    "press_release": r.press_release,
                }
                for r in releases
            ]

    return [
        ReleaseRecord(
            id=0,  # Not included in search results
            fred_release_id=r["fred_release_id"],
            name=r["name"],
            link=r.get("link"),
            press_release=r["press_release"],
        )
        for r in results
    ]


@app.get("/releases/upcoming", response_model=list[ReleaseDateRecord])
def get_upcoming_releases(
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    key_only: Annotated[bool, Query(description="Only official press releases")] = False,
):
    """Get upcoming economic releases from FRED calendar."""
    from src.query import ReleaseQuery

    releases = ReleaseQuery.get_upcoming(days=days, press_release_only=key_only)

    return [
        ReleaseDateRecord(
            fred_release_id=r["fred_release_id"],
            name=r["name"],
            release_date=r["release_date"],
            link=r.get("link"),
            press_release=r["press_release"],
        )
        for r in releases
    ]


@app.get("/releases/today", response_model=list[ReleaseDateRecord])
def get_todays_releases():
    """Get releases scheduled for today."""
    from src.query import ReleaseQuery

    releases = ReleaseQuery.get_today()

    return [
        ReleaseDateRecord(
            fred_release_id=r["fred_release_id"],
            name=r["name"],
            release_date=r["release_date"],
            link=r.get("link"),
            press_release=r["press_release"],
        )
        for r in releases
    ]


class WeeklyReleaseRecord(BaseModel):
    release_date: str
    day_of_week: str
    name: str
    fred_release_id: int
    press_release: bool


@app.get("/releases/week", response_model=list[WeeklyReleaseRecord])
def get_this_weeks_releases(
    key_only: Annotated[bool, Query(description="Only official press releases")] = False,
):
    """Get releases scheduled for this week (Monday-Sunday)."""
    from src.query import ReleaseQuery

    releases = ReleaseQuery.get_this_week(press_release_only=key_only)

    return [
        WeeklyReleaseRecord(
            release_date=r["release_date"],
            day_of_week=r["day_of_week"],
            name=r["name"],
            fred_release_id=r["fred_release_id"],
            press_release=r["press_release"],
        )
        for r in releases
    ]


class ReleaseSummary(BaseModel):
    period_days: int
    total_releases: int
    press_releases: int
    by_date: dict[str, int]


@app.get("/releases/summary", response_model=ReleaseSummary)
def get_release_summary(
    days: Annotated[int, Query(ge=1, le=30)] = 7,
):
    """Get summary of upcoming releases."""
    from src.query import ReleaseQuery

    return ReleaseQuery.get_summary(days=days)


@app.get("/releases/{fred_release_id}", response_model=ReleaseRecord)
def get_release(fred_release_id: int):
    """Get a FRED release by its FRED release ID."""
    from src.db import get_session
    from src.db.models import Release

    with get_session() as session:
        release = session.query(Release).filter(
            Release.fred_release_id == fred_release_id
        ).first()

        if not release:
            raise HTTPException(
                status_code=404,
                detail=f"Release {fred_release_id} not found",
            )

        return ReleaseRecord(
            id=release.id,
            fred_release_id=release.fred_release_id,
            name=release.name,
            link=release.link,
            press_release=release.press_release,
        )


class ReleaseSchedule(BaseModel):
    fred_release_id: int
    name: str
    link: str | None
    notes: str | None
    press_release: bool
    upcoming_dates: list[str]
    next_release: str | None


@app.get("/releases/{fred_release_id}/schedule", response_model=ReleaseSchedule)
def get_release_schedule(
    fred_release_id: int,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
):
    """Get a release and its upcoming schedule."""
    from src.query import ReleaseQuery

    result = ReleaseQuery.get_release_schedule(fred_release_id, days_ahead=days)

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Release {fred_release_id} not found",
        )

    return ReleaseSchedule(**result)


@app.get("/releases/{fred_release_id}/dates", response_model=list[dict])
def get_release_dates(
    fred_release_id: int,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
):
    """Get upcoming release dates for a specific FRED release."""
    from src.db import get_session
    from src.db.models import Release, ReleaseDate

    with get_session() as session:
        release = session.query(Release).filter(
            Release.fred_release_id == fred_release_id
        ).first()

        if not release:
            raise HTTPException(
                status_code=404,
                detail=f"Release {fred_release_id} not found",
            )

        end_date = date.today() + timedelta(days=days)
        dates = (
            session.query(ReleaseDate)
            .filter(
                ReleaseDate.release_id == release.id,
                ReleaseDate.release_date >= date.today(),
                ReleaseDate.release_date <= end_date,
            )
            .order_by(ReleaseDate.release_date)
            .all()
        )

        return [
            {"release_date": rd.release_date.isoformat()}
            for rd in dates
        ]


@app.post("/releases/sync", response_model=ReleaseSyncResult)
def sync_releases(
    days_ahead: Annotated[int, Query(ge=1, le=365)] = 90,
):
    """Sync FRED releases and upcoming release dates."""
    from src.fetchers.fred import FredFetcher

    fetcher = FredFetcher()
    result = fetcher.sync_release_calendar(days_ahead=days_ahead)

    return ReleaseSyncResult(
        releases=result["releases"],
        dates=result["dates"],
    )
