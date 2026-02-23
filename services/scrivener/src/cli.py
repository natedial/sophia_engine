"""CLI interface for Scrivener."""

import logging
from datetime import date, timedelta

import typer
from rich.console import Console
from rich.table import Table

from src.config import get_settings
from src.db import get_engine
from src.db.models import Base

app = typer.Typer(name="scrivener", help="Economic and markets data sourcing platform")
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


@app.command()
def init_db():
    """Initialize the database schema."""
    engine = get_engine()
    console.print("Creating database tables...", style="yellow")
    Base.metadata.create_all(engine)
    console.print("Database initialized successfully!", style="green")


@app.command()
def fetch(
    source: str = typer.Argument(..., help="Data source (fred, bls)"),
    series: str = typer.Argument(..., help="Series ID (e.g., GDP, UNRATE)"),
    start_date: str = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
):
    """Fetch data for a specific series."""
    settings = get_settings()

    # Parse dates
    start = (
        date.fromisoformat(start_date)
        if start_date
        else date.today() - timedelta(days=settings.default_lookback_years * 365)
    )
    end = date.fromisoformat(end_date) if end_date else date.today()

    source_lower = source.lower()
    if source_lower == "fred":
        from src.fetchers.fred import FredFetcher

        fetcher = FredFetcher()
    elif source_lower == "bls":
        from src.fetchers.bls import BlsFetcher

        fetcher = BlsFetcher()
    else:
        console.print(f"Unknown source: {source}", style="red")
        raise typer.Exit(1)

    console.print(f"Fetching {source}:{series} from {start} to {end}...", style="yellow")

    result = fetcher.fetch_and_store(series, start, end)

    if result["status"] == "success":
        console.print(
            f"Success! Fetched {result['records_fetched']} records, "
            f"inserted {result['records_inserted']}",
            style="green",
        )
    else:
        console.print(f"Error: {result.get('error')}", style="red")


@app.command()
def fetch_core(
    source: str = typer.Argument("fred", help="Data source"),
    start_date: str = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
):
    """Fetch all core series for a source."""
    settings = get_settings()

    start = (
        date.fromisoformat(start_date)
        if start_date
        else date.today() - timedelta(days=settings.default_lookback_years * 365)
    )
    end = date.fromisoformat(end_date) if end_date else date.today()

    source_lower = source.lower()

    if source_lower == "fred":
        from src.fetchers.fred import FredFetcher

        fetcher = FredFetcher()
        core_series = fetcher.get_core_series()
        console.print(f"Fetching {len(core_series)} core FRED series...", style="yellow")
        results = fetcher.fetch_multiple(list(core_series.keys()), start, end)

    elif source_lower == "bls":
        from src.fetchers.bls import BlsFetcher

        fetcher = BlsFetcher()
        core_series = fetcher.get_core_series()
        console.print(f"Fetching {len(core_series)} core BLS series (batched)...", style="yellow")
        # BLS uses optimized batch fetching
        results = fetcher.fetch_core_series(start, end)

    else:
        console.print(f"Unknown source: {source}", style="red")
        raise typer.Exit(1)

    # Summary table
    table = Table(title="Fetch Results")
    table.add_column("Series", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Records", justify="right")

    success_count = 0
    for result in results:
        status = result["status"]
        if status == "success":
            success_count += 1
            table.add_row(
                result["external_id"],
                "[green]OK[/green]",
                str(result["records_inserted"]),
            )
        else:
            table.add_row(
                result["external_id"],
                "[red]ERROR[/red]",
                result.get("error", "")[:30],
            )

    console.print(table)
    console.print(f"\nCompleted: {success_count}/{len(results)} series", style="bold")


@app.command()
def list_series(source: str = typer.Argument("fred", help="Data source")):
    """List available core series for a source."""
    source_lower = source.lower()

    if source_lower == "fred":
        from src.fetchers.fred import FredFetcher

        core_series = FredFetcher.get_core_series()
        title = "Core FRED Series"

    elif source_lower == "bls":
        from src.fetchers.bls import BlsFetcher

        core_series = BlsFetcher.get_core_series()
        title = "Core BLS Series"

    else:
        console.print(f"Unknown source: {source}", style="red")
        raise typer.Exit(1)

    table = Table(title=title)
    table.add_column("ID", style="cyan")
    table.add_column("Description", style="white")

    for series_id, description in sorted(core_series.items()):
        table.add_row(series_id, description)

    console.print(table)
    console.print(f"\nTotal: {len(core_series)} series", style="dim")


@app.command()
def config():
    """Show current configuration."""
    settings = get_settings()

    table = Table(title="Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")

    # Show non-sensitive settings
    table.add_row("Database Host", settings.supabase_db_host or "(not set)")
    table.add_row("Database Name", settings.supabase_db_name)
    table.add_row("FRED API Key", "***" if settings.fred_api_key else "(not set)")
    table.add_row("BLS API Key", "***" if settings.bls_api_key else "(not set)")
    table.add_row("Default Lookback", f"{settings.default_lookback_years} years")
    table.add_row("Sweep Time", f"{settings.daily_sweep_hour:02d}:{settings.daily_sweep_minute:02d}")
    table.add_row("Timezone", settings.timezone)

    console.print(table)


@app.command()
def scheduler(
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run as background daemon"),
):
    """Start the scheduler for automated data fetches."""
    from src.scheduler import SchedulerRunner

    console.print("Starting Scrivener scheduler...", style="yellow")
    console.print(f"  Daily sweep: {get_settings().daily_sweep_hour:02d}:{get_settings().daily_sweep_minute:02d} ET")
    console.print(f"  Calendar check: 6am & 6pm ET")
    console.print("\nPress Ctrl+C to stop\n", style="dim")

    runner = SchedulerRunner(blocking=not daemon)

    try:
        runner.start()
    except KeyboardInterrupt:
        console.print("\nShutting down...", style="yellow")
        runner.stop()
        console.print("Scheduler stopped.", style="green")


@app.command()
def sweep(
    source: str = typer.Argument("all", help="Source to sweep (fred, bls, all)"),
):
    """Run an immediate sweep (fetch all core series)."""
    from src.scheduler.jobs import daily_sweep_fred, daily_sweep_bls, daily_sweep_all

    console.print(f"Running immediate sweep: {source}...", style="yellow")

    if source.lower() == "fred":
        result = daily_sweep_fred()
    elif source.lower() == "bls":
        result = daily_sweep_bls()
    elif source.lower() == "all":
        result = daily_sweep_all()
    else:
        console.print(f"Unknown source: {source}", style="red")
        raise typer.Exit(1)

    console.print(f"Sweep complete!", style="green")
    console.print(result)


@app.command()
def auctions(
    days: int = typer.Option(90, "--days", "-d", help="Days of history to fetch"),
    security_type: str = typer.Option(None, "--type", "-t", help="Security type (Bill, Note, Bond, TIPS, FRN)"),
):
    """Fetch Treasury auction data."""
    from datetime import timedelta
    from src.fetchers.treasury import TreasuryFetcher

    fetcher = TreasuryFetcher()
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    console.print(f"Fetching Treasury auctions from {start_date} to {end_date}...", style="yellow")
    if security_type:
        console.print(f"  Filtering by type: {security_type}")

    result = fetcher.fetch_and_store(
        start_date=start_date,
        end_date=end_date,
        security_type=security_type,
    )

    if result["status"] == "success":
        console.print(
            f"Success! Fetched {result['records_fetched']} auctions, "
            f"stored {result['records_stored']}",
            style="green",
        )
    else:
        console.print(f"Error: {result.get('error')}", style="red")


@app.command()
def upcoming_auctions(
    store: bool = typer.Option(False, "--store", "-s", help="Store announced auctions to database"),
):
    """Fetch and display upcoming Treasury auctions from TreasuryDirect."""
    from src.fetchers.treasury import TreasuryFetcher

    fetcher = TreasuryFetcher()

    if store:
        console.print("Fetching announced auctions from TreasuryDirect...", style="yellow")
        result = fetcher.fetch_and_store_announced()

        if result["status"] == "success":
            console.print(
                f"Success! Fetched {result['records_fetched']} announced auctions, "
                f"stored {result['records_stored']}",
                style="green",
            )
        else:
            console.print(f"Error: {result.get('error')}", style="red")
            return

    auctions = fetcher.fetch_announced_auctions()

    if not auctions:
        console.print("No upcoming auctions found", style="yellow")
        return

    table = Table(title="Upcoming Treasury Auctions (TreasuryDirect)")
    table.add_column("Auction Date", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("Term", style="white")
    table.add_column("CUSIP", style="dim")
    table.add_column("Offering ($B)", justify="right", style="green")

    for auction in auctions[:30]:
        offering = auction.get("offeringAmount", "")
        offering_str = ""
        if offering:
            try:
                offering_str = f"{int(offering) / 1_000_000_000:.1f}"
            except (ValueError, TypeError):
                offering_str = ""

        table.add_row(
            auction.get("auctionDate", "")[:10],
            auction.get("securityType", ""),
            auction.get("securityTerm", ""),
            auction.get("cusip", ""),
            offering_str,
        )

    console.print(table)
    console.print(f"\nTotal: {len(auctions)} announced auctions", style="dim")


@app.command()
def releases():
    """List known economic release types."""
    from src.scheduler.calendar import get_release_definitions

    definitions = get_release_definitions()

    table = Table(title="Economic Releases")
    table.add_column("Release", style="cyan")
    table.add_column("Source", style="white")
    table.add_column("Time (ET)", style="white")
    table.add_column("Frequency", style="white")
    table.add_column("Description", style="dim")

    for name, info in sorted(definitions.items()):
        table.add_row(
            name,
            info["source"],
            info["typical_time"],
            info["frequency"],
            info["description"],
        )

    console.print(table)


@app.command()
def sync_releases(
    days: int = typer.Option(90, "--days", "-d", help="Days ahead to sync release dates"),
):
    """Sync FRED releases and upcoming release dates."""
    from src.fetchers.fred import FredFetcher

    console.print(f"Syncing FRED releases and dates ({days} days ahead)...", style="yellow")

    fetcher = FredFetcher()
    result = fetcher.sync_release_calendar(days_ahead=days)

    releases = result["releases"]
    dates = result["dates"]

    console.print(f"\nReleases: {releases['inserted']} new, {releases['updated']} updated", style="green")
    console.print(f"Dates: {dates['inserted']} new, {dates['skipped']} existing", style="green")


@app.command()
def list_releases(
    limit: int = typer.Option(50, "--limit", "-l", help="Max results"),
    search: str = typer.Option(None, "--search", "-s", help="Search by name"),
):
    """List FRED releases from the database."""
    from src.db import get_session
    from src.db.models import Release

    with get_session() as session:
        query = session.query(Release).order_by(Release.name)

        if search:
            query = query.filter(Release.name.ilike(f"%{search}%"))

        releases = query.limit(limit).all()

        if not releases:
            console.print("No releases found. Run 'sync-releases' first.", style="yellow")
            return

        table = Table(title="FRED Releases")
        table.add_column("FRED ID", style="dim", justify="right")
        table.add_column("Name", style="cyan")
        table.add_column("Press Release", style="white")

        for r in releases:
            table.add_row(
                str(r.fred_release_id),
                r.name[:60] + ("..." if len(r.name) > 60 else ""),
                "Yes" if r.press_release else "No",
            )

        console.print(table)
        console.print(f"\nShowing {len(releases)} releases", style="dim")


@app.command()
def upcoming_releases(
    days: int = typer.Option(7, "--days", "-d", help="Days ahead to show"),
):
    """Show upcoming economic releases from FRED calendar."""
    from src.fetchers.fred import FredFetcher

    fetcher = FredFetcher()
    releases = fetcher.get_upcoming_releases(days=days)

    if not releases:
        console.print(f"No upcoming releases in the next {days} day(s)", style="yellow")
        console.print("Tip: Run 'sync-releases' to populate the calendar", style="dim")
        return

    table = Table(title=f"Upcoming Releases (next {days} days)")
    table.add_column("Date", style="cyan")
    table.add_column("Release", style="white")
    table.add_column("Press Release", style="dim")

    for r in releases:
        table.add_row(
            r["release_date"].isoformat(),
            r["name"][:50] + ("..." if len(r["name"]) > 50 else ""),
            "Yes" if r["press_release"] else "No",
        )

    console.print(table)
    console.print(f"\nTotal: {len(releases)} upcoming releases", style="dim")


@app.command()
def upcoming(
    days: int = typer.Option(1, "--days", "-d", help="Number of days to look ahead"),
):
    """Show upcoming economic releases from the calendar."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from src.scheduler.calendar import ReleaseCalendar

    tz = ZoneInfo("America/New_York")
    now = datetime.now(tz)
    end = now + timedelta(days=days)

    calendar = ReleaseCalendar()
    releases = calendar.get_upcoming_releases(start=now, end=end)

    if not releases:
        console.print(f"No mapped releases found in the next {days} day(s)", style="yellow")
        return

    table = Table(title=f"Upcoming Releases (next {days} day(s))")
    table.add_column("Time (ET)", style="cyan")
    table.add_column("Release", style="white")
    table.add_column("Type", style="yellow")
    table.add_column("FRED Series", style="dim")
    table.add_column("BLS Series", style="dim")

    for release in releases:
        time_str = release["scheduled_time"].strftime("%m/%d %H:%M")
        fred = ", ".join(release["fred_series"][:2]) + ("..." if len(release["fred_series"]) > 2 else "")
        bls = ", ".join(release["bls_series"][:2]) + ("..." if len(release["bls_series"]) > 2 else "")

        table.add_row(
            time_str,
            release["release_name"][:40],
            release["release_type"],
            fred or "-",
            bls or "-",
        )

    console.print(table)
    console.print(f"\nTotal: {len(releases)} mapped releases", style="dim")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload"),
):
    """Start the API server."""
    import uvicorn

    console.print(f"Starting Scrivener API on http://{host}:{port}", style="green")
    console.print(f"API docs: http://{host}:{port}/docs", style="dim")

    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def query(
    series_id: str = typer.Argument(..., help="Series ID to query (e.g., GDP, UNRATE)"),
    latest: bool = typer.Option(False, "--latest", "-l", help="Get latest value only"),
    days: int = typer.Option(365, "--days", "-d", help="Days of history"),
):
    """Query a time series."""
    from src.query import SeriesQuery

    if latest:
        result = SeriesQuery.get_latest(series_id)
        if result:
            console.print(f"{series_id}: {result['value']} ({result['date']})")
        else:
            console.print(f"No data found for {series_id}", style="red")
    else:
        from datetime import timedelta
        end = date.today()
        start = end - timedelta(days=days)

        obs = SeriesQuery.get_observations(series_id, start_date=start, end_date=end)

        if not obs:
            console.print(f"No data found for {series_id}", style="red")
            return

        table = Table(title=f"{series_id} ({len(obs)} observations)")
        table.add_column("Date", style="cyan")
        table.add_column("Value", justify="right")

        # Show first 5 and last 5
        display = obs[:5] + [{"date": "...", "value": None}] + obs[-5:] if len(obs) > 10 else obs

        for o in display:
            val = f"{o['value']:.4f}" if o['value'] is not None else "..."
            table.add_row(o["date"], val)

        console.print(table)


@app.command()
def query_auctions(
    days: int = typer.Option(30, "--days", "-d", help="Days of history"),
    security_type: str = typer.Option(None, "--type", "-t", help="Security type filter"),
    summary: bool = typer.Option(False, "--summary", "-s", help="Show summary stats only"),
):
    """Query Treasury auction data."""
    from src.query import AuctionQuery

    if summary:
        stats = AuctionQuery.get_summary_stats(security_type=security_type, days=days)
        console.print(f"\nAuction Summary (last {days} days):", style="bold")
        console.print(f"  Count: {stats['count']}")
        if stats.get('total_offered_millions'):
            console.print(f"  Total Offered: ${stats['total_offered_millions']:,.0f}M")
        if stats.get('avg_yield'):
            console.print(f"  Avg Yield: {stats['avg_yield']:.3f}%")
        if stats.get('avg_bid_to_cover'):
            console.print(f"  Avg Bid/Cover: {stats['avg_bid_to_cover']:.2f}")
        if stats.get('by_type'):
            console.print(f"  By Type: {stats['by_type']}")
    else:
        auctions = AuctionQuery.get_recent(days=days, security_type=security_type, limit=20)

        table = Table(title=f"Recent Auctions (last {days} days)")
        table.add_column("Date", style="cyan")
        table.add_column("Type", style="white")
        table.add_column("Term", style="white")
        table.add_column("Yield", justify="right")
        table.add_column("B/C", justify="right")

        for a in auctions:
            yield_str = f"{a['high_yield']:.3f}%" if a['high_yield'] else "-"
            btc_str = f"{a['bid_to_cover_ratio']:.2f}" if a['bid_to_cover_ratio'] else "-"
            table.add_row(
                a["auction_date"],
                a["security_type"],
                a["security_term"] or "-",
                yield_str,
                btc_str,
            )

        console.print(table)


@app.command()
def seed_speakers():
    """Seed the database with default Fed speakers."""
    from src.fetchers.fed_speeches import FedSpeechFetcher

    fetcher = FedSpeechFetcher()
    count = fetcher.seed_default_speakers()
    console.print(f"Seeded {count} new speakers", style="green")


@app.command()
def list_speakers():
    """List all speakers in the database."""
    from src.db import get_session
    from src.db.models import Speaker

    with get_session() as session:
        speakers = session.query(Speaker).order_by(Speaker.institution, Speaker.name).all()

        if not speakers:
            console.print("No speakers found. Run 'seed-speakers' first.", style="yellow")
            return

        table = Table(title="Speakers")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Institution", style="white")
        table.add_column("Active", style="green")

        for s in speakers:
            table.add_row(
                str(s.id),
                s.name,
                s.title or "-",
                s.institution,
                "Yes" if s.is_active else "No",
            )

        console.print(table)
        console.print(f"\nTotal: {len(speakers)} speakers", style="dim")


@app.command()
def fetch_speech(
    url: str = typer.Argument(..., help="URL of the speech"),
    speaker: str = typer.Option(..., "--speaker", "-s", help="Speaker name"),
    speech_date: str = typer.Option(..., "--date", "-d", help="Speech date (YYYY-MM-DD)"),
    title: str = typer.Option(None, "--title", "-t", help="Speech title"),
    speech_type: str = typer.Option("speech", "--type", help="Type: speech, statement, press_conference"),
    source: str = typer.Option("Federal Reserve", "--source", help="Source institution"),
):
    """Fetch and store a single speech by URL."""
    from src.fetchers.fed_speeches import FedSpeechFetcher

    parsed_date = date.fromisoformat(speech_date)

    with FedSpeechFetcher() as fetcher:
        result = fetcher.fetch_and_store(
            url=url,
            speaker_name=speaker,
            speech_date=parsed_date,
            title=title,
            speech_type=speech_type,
            source=source,
        )

    if result["status"] == "success":
        console.print(
            f"Stored speech: {result['speaker']} ({result['date']}) - "
            f"{result['word_count']} words",
            style="green",
        )
    elif result["status"] == "skipped":
        console.print(f"Speech already exists: {url}", style="yellow")
    else:
        console.print(f"Error: {result.get('error')}", style="red")


@app.command()
def list_speeches(
    speaker: str = typer.Option(None, "--speaker", "-s", help="Filter by speaker name"),
    source: str = typer.Option(None, "--source", help="Filter by source"),
    days: int = typer.Option(90, "--days", "-d", help="Days of history"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
):
    """List speeches in the database."""
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

        speeches = query.order_by(Speech.speech_date.desc()).limit(limit).all()

        if not speeches:
            console.print("No speeches found", style="yellow")
            return

        table = Table(title=f"Speeches (last {days} days)")
        table.add_column("Date", style="cyan")
        table.add_column("Speaker", style="white")
        table.add_column("Title", style="white", max_width=40)
        table.add_column("Type", style="dim")
        table.add_column("Words", justify="right")

        for s in speeches:
            table.add_row(
                s.speech_date.isoformat(),
                s.speaker_name,
                (s.title[:37] + "...") if s.title and len(s.title) > 40 else (s.title or "-"),
                s.speech_type or "-",
                str(s.word_count or 0),
            )

        console.print(table)
        console.print(f"\nTotal: {len(speeches)} speeches", style="dim")


if __name__ == "__main__":
    app()
