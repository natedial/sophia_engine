"""FRED (Federal Reserve Economic Data) fetcher."""

import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from typing import Any

import httpx
from fredapi import Fred
from sqlalchemy import text

from src.db import get_engine, get_session
from src.db.models import Release, ReleaseCalendarSyncRun, ReleaseDate
from src.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

PAGINATION_LIMIT = 1000
RELEASE_DATES_WINDOW_DAYS = 7
RELEASE_DATES_WINDOW_LIMIT = 250
ANCHOR_RELEASES = (
    "Employment Situation",
    "ADP National Employment Report",
)
ANCHOR_VALIDATION_WINDOW_DAYS = 45
RELEASE_CALENDAR_SYNC_LOCK_KEY = 418_033

_release_calendar_sync_lock = Lock()


def _safe_request_error(exc: Exception) -> str:
    """Describe an upstream failure without leaking request URLs or query credentials."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__}:status={exc.response.status_code}"
    return type(exc).__name__


# Key FRED series for initial setup
CORE_SERIES = {
    # GDP & Growth
    "GDP": "Gross Domestic Product",
    "GDPC1": "Real Gross Domestic Product",
    "A191RL1Q225SBEA": "Real GDP Growth Rate",
    # Inflation
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
    "CPILFESL": "Core CPI (Less Food and Energy)",
    "PCEPI": "Personal Consumption Expenditures Price Index",
    "PCEPILFE": "Core PCE Price Index",
    # Employment
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "Total Nonfarm Payrolls",
    "ICSA": "Initial Jobless Claims",
    "CCSA": "Continued Claims",
    "JTSJOL": "Job Openings (JOLTS)",
    # Interest Rates
    "DFF": "Federal Funds Effective Rate (Daily)",
    "FEDFUNDS": "Federal Funds Effective Rate (Monthly)",
    "DFEDTARU": "Federal Funds Target Rate Upper",
    "DFEDTARL": "Federal Funds Target Rate Lower",
    "SOFR": "Secured Overnight Financing Rate",
    # Treasury Yields
    "DGS1MO": "1-Month Treasury",
    "DGS3MO": "3-Month Treasury",
    "DGS6MO": "6-Month Treasury",
    "DGS1": "1-Year Treasury",
    "DGS2": "2-Year Treasury",
    "DGS5": "5-Year Treasury",
    "DGS7": "7-Year Treasury",
    "DGS10": "10-Year Treasury",
    "DGS20": "20-Year Treasury",
    "DGS30": "30-Year Treasury",
    # Spreads
    "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury",
    "T10Y3M": "10-Year Treasury Minus 3-Month Treasury",
    # Other
    "SP500": "S&P 500 Index",
    "DTWEXBGS": "Trade Weighted US Dollar Index",
    "VIXCLS": "CBOE Volatility Index (VIX)",
}


class FredFetcher(BaseFetcher):
    """Fetcher for FRED (Federal Reserve Economic Data)."""

    source_name = "FRED"
    base_url = "https://api.stlouisfed.org/fred"
    rate_limit_per_min = 120

    def __init__(self) -> None:
        super().__init__()
        if not self.settings.fred_api_key:
            raise ValueError("FRED_API_KEY is required. Get one at https://fred.stlouisfed.org/docs/api/api_key.html")
        self._client = Fred(api_key=self.settings.fred_api_key)

    def fetch_series_info(self, external_id: str) -> dict[str, Any]:
        """Fetch series metadata from FRED."""
        info = self._client.get_series_info(external_id)

        # Map FRED frequency codes to human-readable
        freq_map = {
            "D": "daily",
            "W": "weekly",
            "BW": "biweekly",
            "M": "monthly",
            "Q": "quarterly",
            "SA": "semiannual",
            "A": "annual",
        }

        return {
            "name": info.get("title", external_id),
            "description": info.get("notes"),
            "frequency": freq_map.get(info.get("frequency_short"), info.get("frequency")),
            "units": info.get("units"),
            "seasonal_adjustment": info.get("seasonal_adjustment_short"),
            "metadata": {
                "fred_id": info.get("id"),
                "realtime_start": str(info.get("realtime_start")),
                "realtime_end": str(info.get("realtime_end")),
                "observation_start": str(info.get("observation_start")),
                "observation_end": str(info.get("observation_end")),
                "popularity": info.get("popularity"),
            },
        }

    def fetch_observations(
        self,
        external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch observations from FRED."""
        start_date = start_date or self.get_default_start_date()
        end_date = end_date or date.today()

        # fredapi returns a pandas Series
        data = self._client.get_series(
            external_id,
            observation_start=start_date,
            observation_end=end_date,
        )

        observations = []
        for obs_date, value in data.items():
            # Skip NaN values
            if value != value:  # NaN check
                continue
            observations.append({
                "date": obs_date.date() if hasattr(obs_date, "date") else obs_date,
                "value": float(value),
            })

        return observations

    def fetch_with_revisions(
        self,
        external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch observations with revision history (vintage dates).

        This is useful for understanding how data was revised over time.
        """
        start_date = start_date or self.get_default_start_date()
        end_date = end_date or date.today()

        # Get all vintage dates for this series
        vintages = self._client.get_series_all_releases(external_id)

        observations = []
        revision_counts: dict[date, int] = {}
        for _, row in vintages.iterrows():
            if row["value"] != row["value"]:  # NaN check
                continue
            obs_date = row.get("date", row.name)
            if hasattr(obs_date, "date"):
                obs_date = obs_date.date()
            if start_date <= obs_date <= end_date:
                revision_num = revision_counts.get(obs_date, 0)
                revision_counts[obs_date] = revision_num + 1
                observations.append({
                    "date": obs_date,
                    "value": float(row["value"]),
                    "release_date": row.get("realtime_start"),
                    "revision_num": revision_num,
                })

        return observations

    @classmethod
    def get_core_series(cls) -> dict[str, str]:
        """Get the dictionary of core FRED series."""
        return CORE_SERIES.copy()

    def fetch_core_series(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all core series."""
        return self.fetch_multiple(
            list(CORE_SERIES.keys()),
            start_date=start_date,
            end_date=end_date,
        )

    def search_series_candidates(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search FRED for candidate series matching a free-text query."""
        results = self._client.search(query, limit=limit)
        candidates: list[dict[str, Any]] = []
        try:
            iterator = results.iterrows()
        except AttributeError:
            return candidates

        for external_id, row in iterator:
            candidate = {
                "external_id": str(external_id),
                "name": row.get("title") or str(external_id),
                "description": row.get("notes"),
                "source": self.source_name,
                "frequency": row.get("frequency"),
                "units": row.get("units"),
            }
            candidates.append(candidate)
        return candidates

    # -------------------------------------------------------------------------
    # Release Calendar Methods
    # -------------------------------------------------------------------------

    def _api_request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a direct API request to FRED."""
        url = f"{self.base_url}/{endpoint}"
        default_params = {
            "api_key": self.settings.fred_api_key,
            "file_type": "json",
        }
        if params:
            default_params.update(params)

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=default_params)
            response.raise_for_status()
            return response.json()

    @contextmanager
    def _acquire_release_calendar_sync_lock(self) -> Any:
        """Acquire a non-blocking single-flight lock for release calendar sync."""
        local_lock_acquired = _release_calendar_sync_lock.acquire(blocking=False)
        if not local_lock_acquired:
            yield {
                "acquired": False,
                "reason": "local_lock_not_acquired",
            }
            return

        connection = None
        advisory_lock_acquired = False
        try:
            engine = get_engine()
            if engine.dialect.name == "postgresql":
                connection = engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                advisory_lock_acquired = bool(
                    connection.execute(
                        text("SELECT pg_try_advisory_lock(:lock_key)"),
                        {"lock_key": RELEASE_CALENDAR_SYNC_LOCK_KEY},
                    ).scalar()
                )
                if not advisory_lock_acquired:
                    yield {
                        "acquired": False,
                        "reason": "postgres_advisory_lock_not_acquired",
                    }
                    return

            yield {
                "acquired": True,
                "reason": None,
            }
        finally:
            try:
                if connection is not None and advisory_lock_acquired:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": RELEASE_CALENDAR_SYNC_LOCK_KEY},
                    )
            finally:
                if connection is not None:
                    connection.close()
                if local_lock_acquired:
                    _release_calendar_sync_lock.release()

    def _record_release_calendar_sync_run(
        self,
        *,
        started_at: datetime,
        completed_at: datetime,
        days_ahead: int,
        result: dict[str, Any],
        error_message: str | None = None,
        lock_acquired: bool,
    ) -> None:
        """Persist an audit record for a release calendar sync attempt."""
        releases = result.get("releases", {})
        dates = result.get("dates", {})
        anchor_validation = dates.get("anchor_validation", {})
        sync_run = ReleaseCalendarSyncRun(
            started_at=started_at,
            completed_at=completed_at,
            days_ahead=days_ahead,
            status=result.get("status", "error"),
            ready=bool(result.get("ready")),
            lock_acquired=lock_acquired,
            releases_fetched=releases.get("fetched"),
            releases_expected=releases.get("expected"),
            releases_inserted=releases.get("inserted"),
            releases_updated=releases.get("updated"),
            dates_fetched=dates.get("fetched"),
            dates_expected=dates.get("expected"),
            dates_inserted=dates.get("inserted"),
            dates_skipped=dates.get("skipped"),
            dates_skipped_missing_release=dates.get("skipped_missing_release"),
            dates_removed=dates.get("removed"),
            dates_complete=dates.get("complete"),
            destructive_cleanup_performed=dates.get("destructive_cleanup_performed"),
            integrity_ok=dates.get("integrity_ok"),
            degraded_reason=dates.get("degraded_reason") or result.get("degraded_reason"),
            missing_anchors=anchor_validation.get("missing_releases"),
            error_message=error_message,
        )
        with get_session() as session:
            session.add(sync_run)

    @staticmethod
    def _empty_release_sync_result(status: str) -> dict[str, Any]:
        """Build a default sync section for runs that never reached a fetch."""
        return {
            "fetched": 0,
            "expected": None,
            "inserted": 0,
            "updated": 0,
            "complete": False,
            "status": status,
            "degraded_reason": None,
        }

    @staticmethod
    def _empty_release_date_sync_result(status: str, degraded_reason: str | None) -> dict[str, Any]:
        """Build a default date-sync section for runs that never reached reconciliation."""
        return {
            "fetched": 0,
            "expected": None,
            "inserted": 0,
            "skipped": 0,
            "skipped_missing_release": 0,
            "removed": 0,
            "complete": False,
            "status": status,
            "degraded_reason": degraded_reason,
            "destructive_cleanup_performed": False,
            "integrity_ok": False,
            "anchor_validation": {
                "enabled": False,
                "ok": False,
                "checked_until": None,
                "missing_releases": [],
            },
        }

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        """Convert FRED pagination metadata values to integers when possible."""
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _collect_paginated(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None,
        item_key: str,
        limit: int = PAGINATION_LIMIT,
    ) -> dict[str, Any]:
        """Collect all pages from a paginated FRED endpoint."""
        collected: list[dict[str, Any]] = []
        expected_count: int | None = None
        offset = 0
        page_count = 0
        incomplete_reason: str | None = None

        while True:
            page_params = dict(params or {})
            page_params["limit"] = str(limit)
            page_params["offset"] = str(offset)

            try:
                data = self._api_request(endpoint, page_params)
            except Exception as exc:
                if not collected:
                    raise
                safe_error = _safe_request_error(exc)
                incomplete_reason = f"request_failed:{safe_error}"
                logger.warning(
                    "FRED pagination degraded for %s at offset=%s: %s",
                    endpoint,
                    offset,
                    safe_error,
                )
                break

            page_count += 1
            page_items = data.get(item_key, [])
            response_count = self._coerce_int(data.get("count"))
            response_limit = self._coerce_int(data.get("limit")) or limit
            response_offset = self._coerce_int(data.get("offset"))
            if response_offset is None:
                response_offset = offset

            if expected_count is None:
                expected_count = response_count
            elif response_count is not None and response_count != expected_count:
                incomplete_reason = "count_changed_during_pagination"
                logger.warning(
                    "FRED pagination degraded for %s: count changed from %s to %s",
                    endpoint,
                    expected_count,
                    response_count,
                )
                break

            collected.extend(page_items)
            fetched_count = len(collected)

            if expected_count is None:
                if len(page_items) < response_limit:
                    break
                offset = response_offset + response_limit
                continue

            if fetched_count >= expected_count:
                if fetched_count > expected_count:
                    incomplete_reason = "fetched_more_rows_than_reported"
                    logger.warning(
                        "FRED pagination degraded for %s: fetched=%s expected=%s",
                        endpoint,
                        fetched_count,
                        expected_count,
                    )
                break

            if not page_items:
                incomplete_reason = "empty_page_before_expected_count"
                logger.warning(
                    "FRED pagination degraded for %s: "
                    "empty page before expected count (fetched=%s expected=%s)",
                    endpoint,
                    fetched_count,
                    expected_count,
                )
                break

            if len(page_items) < response_limit:
                incomplete_reason = "short_page_before_expected_count"
                logger.warning(
                    "FRED pagination degraded for %s: "
                    "short page before expected count (fetched=%s expected=%s)",
                    endpoint,
                    fetched_count,
                    expected_count,
                )
                break

            offset = response_offset + response_limit

        complete = incomplete_reason is None and (
            expected_count is None or len(collected) == expected_count
        )
        return {
            "items": collected,
            "fetched_count": len(collected),
            "expected_count": expected_count,
            "page_count": page_count,
            "complete": complete,
            "degraded_reason": incomplete_reason,
        }

    def _collect_release_dates_by_window(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Collect all-release date snapshots in smaller windows to avoid oversized fetches."""
        collected: list[dict[str, Any]] = []
        expected_count_total = 0
        all_expected_counts_known = True
        page_count = 0
        complete = True
        degraded_reason: str | None = None

        current_start = start_date
        while current_start <= end_date:
            current_end = min(
                current_start + timedelta(days=RELEASE_DATES_WINDOW_DAYS - 1),
                end_date,
            )
            window_params = {
                "include_release_dates_with_no_data": "true",
                "realtime_start": current_start.isoformat(),
                "realtime_end": current_end.isoformat(),
            }

            try:
                snapshot = self._collect_paginated(
                    "releases/dates",
                    params=window_params,
                    item_key="release_dates",
                    limit=RELEASE_DATES_WINDOW_LIMIT,
                )
            except Exception as exc:
                complete = False
                safe_error = _safe_request_error(exc)
                if degraded_reason is None:
                    degraded_reason = (
                        "request_failed:"
                        f"{current_start.isoformat()}:{current_end.isoformat()}:{safe_error}"
                    )
                logger.warning(
                    "FRED release-date window failed for %s to %s: %s",
                    current_start,
                    current_end,
                    safe_error,
                )
                break

            collected.extend(snapshot["items"])
            page_count += snapshot["page_count"]
            if snapshot["expected_count"] is None:
                all_expected_counts_known = False
            else:
                expected_count_total += snapshot["expected_count"]

            if not snapshot["complete"]:
                complete = False
                if degraded_reason is None:
                    degraded_reason = (
                        "window_degraded:"
                        f"{current_start.isoformat()}:{current_end.isoformat()}:"
                        f"{snapshot['degraded_reason']}"
                    )
                logger.warning(
                    "FRED release-date window degraded for %s to %s: %s",
                    current_start,
                    current_end,
                    snapshot["degraded_reason"],
                )
                break

            current_start = current_end + timedelta(days=1)

        return {
            "items": collected,
            "fetched_count": len(collected),
            "expected_count": expected_count_total if all_expected_counts_known else None,
            "page_count": page_count,
            "complete": complete,
            "degraded_reason": degraded_reason,
            "windowed": True,
        }

    def fetch_releases(self) -> dict[str, Any]:
        """Fetch all FRED releases (economic data release categories).

        Returns releases with pagination metadata.
        """
        snapshot = self._collect_paginated(
            "releases",
            params=None,
            item_key="releases",
        )
        releases = snapshot["items"]

        return {
            **snapshot,
            "releases": [
                {
                    "fred_release_id": r["id"],
                    "name": r["name"],
                    "link": r.get("link"),
                    "notes": r.get("notes"),
                    "press_release": r.get("press_release", True),
                }
                for r in releases
            ],
        }

    def fetch_release_dates(
        self,
        release_id: int | None = None,
        days_ahead: int = 30,
        include_past: bool = False,
    ) -> dict[str, Any]:
        """Fetch release dates from FRED.

        Args:
            release_id: Specific release ID, or None for all releases
            days_ahead: Number of days ahead to look
            include_past: If True, include past release dates

        Returns:
            Release date records with pagination metadata
        """
        today = date.today()
        params: dict[str, str] = {
            "include_release_dates_with_no_data": "true",
        }

        if release_id:
            # Fetch dates for specific release
            endpoint = "release/dates"
            params["release_id"] = str(release_id)
        else:
            # Fetch all upcoming release dates
            endpoint = "releases/dates"

        if not include_past:
            params["realtime_start"] = today.isoformat()
            params["realtime_end"] = (today + timedelta(days=days_ahead)).isoformat()

        if release_id is None and not include_past:
            snapshot = self._collect_release_dates_by_window(
                start_date=today,
                end_date=today + timedelta(days=days_ahead),
            )
        else:
            snapshot = self._collect_paginated(
                endpoint,
                params=params,
                item_key="release_dates",
            )
        release_dates = snapshot["items"]

        return {
            **snapshot,
            "release_dates": [
                {
                    "fred_release_id": rd["release_id"],
                    "release_name": rd.get("release_name", ""),
                    "release_date": date.fromisoformat(rd["date"]),
                }
                for rd in release_dates
            ],
        }

    def sync_releases(self) -> dict[str, Any]:
        """Sync all FRED releases to the database.

        Returns:
            Dict with counts of inserted/updated releases
        """
        snapshot = self.fetch_releases()
        releases = snapshot["releases"]
        inserted = 0
        updated = 0

        with get_session() as session:
            for r in releases:
                existing = session.query(Release).filter_by(
                    fred_release_id=r["fred_release_id"]
                ).first()

                if existing:
                    # Update existing
                    existing.name = r["name"]
                    existing.link = r["link"]
                    existing.notes = r["notes"]
                    existing.press_release = r["press_release"]
                    updated += 1
                else:
                    # Insert new
                    release = Release(
                        fred_release_id=r["fred_release_id"],
                        name=r["name"],
                        link=r["link"],
                        notes=r["notes"],
                        press_release=r["press_release"],
                    )
                    session.add(release)
                    inserted += 1

            session.commit()

        status = "complete" if snapshot["complete"] else "degraded"
        logger.info(
            "Synced releases: fetched=%s expected=%s inserted=%s updated=%s status=%s reason=%s",
            snapshot["fetched_count"],
            snapshot["expected_count"],
            inserted,
            updated,
            status,
            snapshot["degraded_reason"],
        )
        return {
            "fetched": snapshot["fetched_count"],
            "expected": snapshot["expected_count"],
            "inserted": inserted,
            "updated": updated,
            "complete": snapshot["complete"],
            "status": status,
            "degraded_reason": snapshot["degraded_reason"],
        }

    @staticmethod
    def _validate_anchor_release_dates(
        release_dates: list[dict[str, Any]],
        *,
        days_ahead: int,
    ) -> dict[str, Any]:
        """Validate that key anchor releases still have upcoming dates."""
        validation_days = min(days_ahead, ANCHOR_VALIDATION_WINDOW_DAYS)
        if validation_days < ANCHOR_VALIDATION_WINDOW_DAYS:
            return {
                "enabled": False,
                "ok": True,
                "checked_until": None,
                "missing_releases": [],
            }

        today = date.today()
        validation_end = today + timedelta(days=validation_days)
        observed_names = {
            str(row.get("release_name", "")).strip()
            for row in release_dates
            if today <= row.get("release_date", today - timedelta(days=1)) <= validation_end
        }
        missing_releases = [
            release_name
            for release_name in ANCHOR_RELEASES
            if release_name not in observed_names
        ]
        return {
            "enabled": True,
            "ok": not missing_releases,
            "checked_until": validation_end.isoformat(),
            "missing_releases": missing_releases,
        }

    def sync_release_dates(self, days_ahead: int = 90) -> dict[str, Any]:
        """Sync upcoming release dates to the database.

        Args:
            days_ahead: Number of days ahead to sync

        Returns:
            Dict with counts and sync safety metadata
        """
        snapshot = self.fetch_release_dates(days_ahead=days_ahead)
        release_dates = snapshot["release_dates"]
        inserted = 0
        skipped = 0
        removed = 0
        skipped_missing_release = 0
        today = date.today()
        end_date = today + timedelta(days=days_ahead)
        anchor_validation = self._validate_anchor_release_dates(
            release_dates,
            days_ahead=days_ahead,
        )
        destructive_cleanup_allowed = snapshot["complete"] and anchor_validation["ok"]

        with get_session() as session:
            # Build a map of fred_release_id -> release.id
            releases = {r.fred_release_id: r.id for r in session.query(Release).all()}
            desired_dates_by_release: dict[int, set[date]] = {}

            for rd in release_dates:
                fred_id = rd["fred_release_id"]
                if fred_id not in releases:
                    # Release not in our database, skip
                    skipped += 1
                    skipped_missing_release += 1
                    continue

                release_id = releases[fred_id]
                release_date_val = rd["release_date"]
                desired_dates_by_release.setdefault(release_id, set()).add(release_date_val)

            desired_release_ids = set(desired_dates_by_release)
            existing_rows_for_desired = []
            if desired_release_ids:
                existing_rows_for_desired = (
                    session.query(ReleaseDate)
                    .filter(
                        ReleaseDate.release_id.in_(desired_release_ids),
                        ReleaseDate.release_date >= today,
                        ReleaseDate.release_date <= end_date,
                    )
                    .all()
                )
            existing_dates_by_release: dict[int, set[date]] = {}
            for row in existing_rows_for_desired:
                existing_dates_by_release.setdefault(row.release_id, set()).add(
                    row.release_date
                )

            for release_id, desired_dates in desired_dates_by_release.items():
                existing_dates = existing_dates_by_release.get(release_id, set())
                for release_date_val in desired_dates:
                    if release_date_val in existing_dates:
                        skipped += 1
                        continue
                    session.add(
                        ReleaseDate(
                            release_id=release_id,
                            release_date=release_date_val,
                        )
                    )
                    inserted += 1

            if skipped_missing_release:
                destructive_cleanup_allowed = False

            if destructive_cleanup_allowed:
                existing_rows = (
                    session.query(ReleaseDate)
                    .filter(
                        ReleaseDate.release_date >= today,
                        ReleaseDate.release_date <= end_date,
                    )
                    .all()
                )
                for row in existing_rows:
                    desired_dates = desired_dates_by_release.get(row.release_id, set())
                    if row.release_date not in desired_dates:
                        session.delete(row)
                        removed += 1

            session.commit()

        status = "complete" if destructive_cleanup_allowed else "degraded"
        degraded_reason = snapshot["degraded_reason"]
        if degraded_reason is None and not anchor_validation["ok"]:
            degraded_reason = "anchor_validation_failed"
        if degraded_reason is None and skipped_missing_release:
            degraded_reason = "missing_release_catalog_entries"
        logger.info(
            "Synced release dates: fetched=%s expected=%s inserted=%s skipped=%s "
            "skipped_missing_release=%s removed=%s status=%s reason=%s cleanup=%s "
            "missing_anchors=%s",
            snapshot["fetched_count"],
            snapshot["expected_count"],
            inserted,
            skipped,
            skipped_missing_release,
            removed,
            status,
            degraded_reason,
            destructive_cleanup_allowed,
            anchor_validation["missing_releases"],
        )
        return {
            "fetched": snapshot["fetched_count"],
            "expected": snapshot["expected_count"],
            "inserted": inserted,
            "skipped": skipped,
            "skipped_missing_release": skipped_missing_release,
            "removed": removed,
            "complete": snapshot["complete"],
            "status": status,
            "degraded_reason": degraded_reason,
            "destructive_cleanup_performed": destructive_cleanup_allowed,
            "integrity_ok": anchor_validation["ok"],
            "anchor_validation": anchor_validation,
        }

    def get_upcoming_releases(self, days: int = 7) -> list[dict[str, Any]]:
        """Get upcoming releases from the database.

        Args:
            days: Number of days ahead to look

        Returns:
            List of upcoming releases with dates
        """
        today = date.today()
        end_date = today + timedelta(days=days)

        with get_session() as session:
            results = (
                session.query(Release, ReleaseDate)
                .join(ReleaseDate)
                .filter(
                    ReleaseDate.release_date >= today,
                    ReleaseDate.release_date <= end_date,
                )
                .order_by(ReleaseDate.release_date)
                .all()
            )

            return [
                {
                    "fred_release_id": release.fred_release_id,
                    "name": release.name,
                    "release_date": rd.release_date,
                    "link": release.link,
                    "press_release": release.press_release,
                }
                for release, rd in results
            ]

    def sync_release_calendar(self, days_ahead: int = 90) -> dict[str, Any]:
        """Full sync of releases and upcoming dates.

        Args:
            days_ahead: Number of days ahead to sync dates

        Returns:
            Combined sync results
        """
        logger.info("Starting full release calendar sync...")
        started_at = datetime.now(UTC)
        lock_acquired = False
        result: dict[str, Any] | None = None
        error_message: str | None = None

        try:
            with self._acquire_release_calendar_sync_lock() as lock_state:
                lock_acquired = bool(lock_state["acquired"])
                if not lock_acquired:
                    result = {
                        "status": "degraded",
                        "ready": False,
                        "degraded_reason": lock_state["reason"],
                        "releases": self._empty_release_sync_result(status="skipped"),
                        "dates": self._empty_release_date_sync_result(
                            status="degraded",
                            degraded_reason=lock_state["reason"],
                        ),
                    }
                    logger.warning(
                        "Skipping release calendar sync because lock was not acquired: %s",
                        lock_state["reason"],
                    )
                    return result

                releases_result = self.sync_releases()
                dates_result = self.sync_release_dates(days_ahead=days_ahead)
                result = {
                    "status": (
                        "complete"
                        if releases_result["status"] == "complete"
                        and dates_result["status"] == "complete"
                        else "degraded"
                    ),
                    "ready": dates_result["status"] == "complete",
                    "degraded_reason": dates_result.get("degraded_reason"),
                    "releases": releases_result,
                    "dates": dates_result,
                }
                return result
        except Exception as exc:
            error_message = _safe_request_error(exc)
            result = {
                "status": "error",
                "ready": False,
                "degraded_reason": error_message,
                "releases": self._empty_release_sync_result(status="error"),
                "dates": self._empty_release_date_sync_result(
                    status="error",
                    degraded_reason=error_message,
                ),
            }
            raise
        finally:
            completed_at = datetime.now(UTC)
            if result is not None:
                try:
                    self._record_release_calendar_sync_run(
                        started_at=started_at,
                        completed_at=completed_at,
                        days_ahead=days_ahead,
                        result=result,
                        error_message=error_message,
                        lock_acquired=lock_acquired,
                    )
                except Exception as audit_exc:
                    logger.warning(
                        "Failed to record release calendar sync audit: %s",
                        type(audit_exc).__name__,
                    )
