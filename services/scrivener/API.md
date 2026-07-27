# Scrivener API Documentation

Base URL: `http://localhost:8000` (default)

Interactive docs available at `/docs` when the server is running.

---

## Health

### GET /health

Health check endpoint.

**Response:**
```json
{"status": "ok"}
```

---

## Series

### GET /series

List all available time series.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `source` | string | Filter by source (FRED, BLS) |

**Response:**
```json
[
  {
    "id": 1,
    "external_id": "GDP",
    "name": "Gross Domestic Product",
    "source": "FRED",
    "frequency": "quarterly",
    "units": "Billions of Dollars"
  }
]
```

---

### GET /series/search

Search for series by name or description.

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | Yes | Search term |
| `source` | string | No | Filter by source |
| `limit` | int | No | Max results (default: 20, max: 100) |

**Response:**
```json
[
  {
    "id": 1,
    "external_id": "GDP",
    "name": "Gross Domestic Product",
    "description": "...",
    "source": "FRED"
  }
]
```

---

### GET /series/{series_id}

Get metadata for a specific series.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `series_id` | string | Series ID (e.g., GDP, UNRATE) |

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `source` | string | Source filter (if series exists in multiple sources) |

**Response:**
```json
{
  "id": 1,
  "external_id": "GDP",
  "name": "Gross Domestic Product",
  "description": "Gross Domestic Product",
  "frequency": "quarterly",
  "units": "Billions of Dollars",
  "source": "FRED",
  "last_updated": "2025-12-29T10:00:00Z"
}
```

---

### GET /series/{series_id}/latest

Get the most recent value for a series.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `series_id` | string | Series ID |

**Response:**
```json
{
  "series_id": "FEDFUNDS",
  "date": "2025-11-01",
  "value": 3.88
}
```

---

### GET /series/{series_id}/observations

Get time series observations within a date range.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `series_id` | string | Series ID |

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `start_date` | date | Start date (YYYY-MM-DD) |
| `end_date` | date | End date (YYYY-MM-DD) |
| `source` | string | Source filter |
| `limit` | int | Max observations (max: 10000) |

**Response:**
```json
[
  {"date": "2025-01-01", "value": 30042.113},
  {"date": "2025-04-01", "value": 30485.729},
  {"date": "2025-07-01", "value": 31095.089}
]
```

---

### GET /series/{series_id}/change

Calculate change from N periods ago.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `series_id` | string | Series ID |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `periods` | int | 1 | Number of periods back (1-100) |
| `pct` | bool | true | Return percentage change |

**Response:**
```json
{
  "series_id": "GDP",
  "current_date": "2025-07-01",
  "current_value": 31095.089,
  "previous_date": "2025-04-01",
  "previous_value": 30485.729,
  "change": 1.998,
  "change_type": "pct"
}
```

---

### POST /series/batch/latest

Get latest values for multiple series at once.

**Request Body:**
```json
["GDP", "UNRATE", "FEDFUNDS", "DGS10"]
```

**Response:**
```json
{
  "GDP": {"series_id": "GDP", "date": "2025-07-01", "value": 31095.089},
  "UNRATE": {"series_id": "UNRATE", "date": "2025-11-01", "value": 4.2},
  "FEDFUNDS": {"series_id": "FEDFUNDS", "date": "2025-11-01", "value": 3.88},
  "DGS10": {"series_id": "DGS10", "date": "2025-12-27", "value": 4.58}
}
```

---

## Auctions

### GET /auctions

Get recent Treasury auction results.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 30 | Days of history (1-365) |
| `security_type` | string | null | Filter: Bill, Note, Bond, TIPS, FRN |
| `limit` | int | null | Max results (max: 1000) |

**Response:**
```json
[
  {
    "cusip": "912797KP3",
    "security_type": "Bill",
    "security_term": "4-Week",
    "auction_date": "2025-12-23",
    "issue_date": "2025-12-26",
    "maturity_date": "2026-01-23",
    "high_yield": 4.285,
    "high_discount_rate": 4.22,
    "bid_to_cover_ratio": 2.89,
    "offering_amount": 75000000000,
    "total_accepted": 75000000000,
    "total_tendered": 216975000000,
    "primary_dealer_accepted": 54000000000,
    "direct_bidder_accepted": 3500000000,
    "indirect_bidder_accepted": 17500000000,
    "reopening": false
  }
]
```

---

### GET /auctions/summary

Get summary statistics for recent auctions.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 30 | Days to analyze (1-365) |
| `security_type` | string | null | Filter by type |

**Response:**
```json
{
  "count": 37,
  "period_days": 30,
  "total_offered_millions": 2463025.0,
  "avg_yield": 3.6792,
  "min_yield": 3.517,
  "max_yield": 3.813,
  "avg_bid_to_cover": 2.94,
  "by_type": {"Bill": 28, "Note": 7, "Bond": 2}
}
```

---

### GET /auctions/cusip/{cusip}

Get auction history for a specific CUSIP.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `cusip` | string | 9-character CUSIP identifier |

**Response:**
```json
[
  {
    "cusip": "912797KP3",
    "security_type": "Bill",
    "auction_date": "2025-12-23",
    ...
  }
]
```

---

### GET /auctions/yields/{security_type}/{term}

Get yield history for a specific security type and term.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `security_type` | string | Bill, Note, Bond, etc. |
| `term` | string | e.g., "10-Year", "2-Year", "13-Week" |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 365 | Days of history (1-3650) |

**Response:**
```json
[
  {"date": "2025-01-15", "yield": 4.125, "bid_to_cover": 2.45},
  {"date": "2025-02-15", "yield": 4.089, "bid_to_cover": 2.51},
  {"date": "2025-03-15", "yield": 4.210, "bid_to_cover": 2.38}
]
```

---

### GET /auctions/latest/{security_type}/{term}

Get the most recent auction for a security type/term.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `security_type` | string | Bill, Note, Bond, etc. |
| `term` | string | e.g., "10-Year" |

**Response:**
```json
{
  "cusip": "91282CKL5",
  "security_type": "Note",
  "security_term": "10-Year",
  "auction_date": "2025-12-09",
  "high_yield": 4.235,
  "bid_to_cover_ratio": 2.55,
  ...
}
```

---

## Speakers

### GET /speakers

List all central bank speakers.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `institution` | string | null | Filter by institution |
| `active_only` | bool | true | Only show active speakers |

**Response:**
```json
[
  {
    "id": 1,
    "name": "Jerome H. Powell",
    "title": "Chair",
    "institution": "Federal Reserve",
    "is_active": true
  },
  {
    "id": 2,
    "name": "Philip N. Jefferson",
    "title": "Vice Chair",
    "institution": "Federal Reserve",
    "is_active": true
  }
]
```

---

### GET /speakers/{speaker_id}

Get a speaker by ID.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `speaker_id` | int | Speaker ID |

**Response:**
```json
{
  "id": 1,
  "name": "Jerome H. Powell",
  "title": "Chair",
  "institution": "Federal Reserve",
  "is_active": true
}
```

---

## Speeches

### GET /speeches

List speeches with optional filters.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `speaker` | string | null | Filter by speaker name (partial match) |
| `source` | string | null | Filter by source institution |
| `speech_type` | string | null | Filter: speech, statement, press_conference |
| `days` | int | 90 | Days of history (1-3650) |
| `limit` | int | 100 | Max results (max: 1000) |

**Response:**
```json
[
  {
    "id": 1,
    "url": "https://www.federalreserve.gov/newsevents/speech/jefferson20251107a.htm",
    "speaker_name": "Philip N. Jefferson",
    "title": "Economic Outlook and Monetary Policy",
    "speech_date": "2025-11-07",
    "speech_type": "speech",
    "source": "Federal Reserve",
    "word_count": 1983
  }
]
```

---

### GET /speeches/{speech_id}

Get a speech by ID, including full text.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `speech_id` | int | Speech ID |

**Response:**
```json
{
  "id": 1,
  "url": "https://www.federalreserve.gov/newsevents/speech/jefferson20251107a.htm",
  "speaker_name": "Philip N. Jefferson",
  "title": "Economic Outlook and Monetary Policy",
  "speech_date": "2025-11-07",
  "speech_type": "speech",
  "source": "Federal Reserve",
  "word_count": 1983,
  "raw_text": "Thank you for the opportunity to speak with you today...",
  "content_type": "html",
  "scraped_at": "2025-12-29T20:54:37Z"
}
```

---

### GET /speeches/by-url

Get a speech by its URL.

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Full URL of the speech |

**Response:** Same as GET /speeches/{speech_id}

---

### GET /speeches/speaker/{speaker_name}

Get speeches by a specific speaker.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `speaker_name` | string | Speaker name (partial match supported) |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Max results (max: 100) |

**Response:**
```json
[
  {
    "id": 1,
    "url": "https://...",
    "speaker_name": "Philip N. Jefferson",
    "title": "Economic Outlook and Monetary Policy",
    "speech_date": "2025-11-07",
    "speech_type": "speech",
    "source": "Federal Reserve",
    "word_count": 1983
  }
]
```

---

## Speaker Events

Upcoming Federal Reserve Board communications from the official Board calendar JSON feed (`https://www.federalreserve.gov/json/calendar.json`). Stores speeches, testimony, discussions, FOMC meetings, and press conferences. Statistical releases are skipped (use the FRED release calendar).

### GET /speaker-events

List Fed Board speaker / communications calendar events.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 30 | Lookahead window in days |
| `speaker` | string | null | Filter by speaker name (partial match) |
| `event_type` | string | null | `speech`, `testimony`, `discussion`, `press_conference`, `fomc`, `other` |
| `status` | string | scheduled | `scheduled`, `completed`, `cancelled`, `rescheduled` |
| `limit` | int | 100 | Max results (max: 1000) |

**Response:**
```json
[
  {
    "id": 1,
    "external_id": "fedcal:abc123",
    "speaker_id": 2,
    "speaker_name": "Philip N. Jefferson",
    "title": "Speech - Vice Chair Philip N. Jefferson",
    "event_type": "speech",
    "scheduled_start": "2026-07-16T19:00:00-04:00",
    "scheduled_end": null,
    "location": "At Stanford, California",
    "description": "Navigating Economic Shocks",
    "url": "https://www.youtube.com/watch?v=example",
    "source": "Federal Reserve Board",
    "status": "scheduled",
    "speech_id": null
  }
]
```

---

### GET /speaker-events/upcoming

Get upcoming scheduled Fed speaker calendar events.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 14 | Days ahead |
| `speaker` | string | null | Filter by speaker name |
| `event_type` | string | null | Filter by event type |
| `limit` | int | 100 | Max results |

**Response:** Same shape as `GET /speaker-events`.

---

### GET /speaker-events/{event_id}

Get a speaker calendar event by ID.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `event_id` | int | Speaker event ID |

**Response:** Single event object (same fields as list items).

---

### POST /speaker-events/sync

Sync Fed Board speaker calendar events from `calendar.json`.
Requires `X-Scrivener-API-Key` matching the configured `SCRIVENER_API_KEY`.

**Response:**
```json
{
  "status": "complete",
  "ready": true,
  "events_fetched": 2500,
  "events_kept": 780,
  "events_inserted": 12,
  "events_updated": 768,
  "events_cancelled": 1,
  "events_skipped": 1720,
  "error_message": null
}
```

Returns `503` when sync is not ready (fetch/parse failure).

---

## Releases

Economic data release calendar from FRED. Use these endpoints to query upcoming economic data releases.

### GET /releases

List all FRED releases.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | null | Search by release name |
| `limit` | int | 100 | Max results (max: 500) |

**Response:**
```json
[
  {
    "id": 1,
    "fred_release_id": 10,
    "name": "Consumer Price Index",
    "link": "https://www.bls.gov/cpi/",
    "press_release": true
  }
]
```

---

### GET /releases/upcoming

Get upcoming economic releases.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 7 | Days ahead (1-90) |
| `key_only` | bool | false | Only official press releases (major indicators) |

**Response:**
```json
[
  {
    "fred_release_id": 10,
    "name": "Consumer Price Index",
    "release_date": "2026-01-10",
    "link": "https://www.bls.gov/cpi/",
    "press_release": true
  },
  {
    "fred_release_id": 50,
    "name": "Employment Situation",
    "release_date": "2026-01-10",
    "link": "https://www.bls.gov/ces/",
    "press_release": true
  }
]
```

---

### GET /releases/today

Get releases scheduled for today.

**Response:**
```json
[
  {
    "fred_release_id": 21,
    "name": "H.15 Selected Interest Rates",
    "release_date": "2025-12-29",
    "link": "https://www.federalreserve.gov/releases/h15/",
    "press_release": true
  }
]
```

---

### GET /releases/week

Get releases for the current week (Monday-Sunday).

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `key_only` | bool | false | Only official press releases |

**Response:**
```json
[
  {
    "release_date": "2025-12-30",
    "day_of_week": "Monday",
    "name": "Consumer Price Index",
    "fred_release_id": 10,
    "press_release": true
  },
  {
    "release_date": "2025-12-31",
    "day_of_week": "Tuesday",
    "name": "Employment Situation",
    "fred_release_id": 50,
    "press_release": true
  }
]
```

---

### GET /releases/summary

Get summary of upcoming releases.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 7 | Days ahead (1-30) |

**Response:**
```json
{
  "period_days": 7,
  "total_releases": 181,
  "press_releases": 74,
  "by_date": {
    "2025-12-29": 34,
    "2025-12-30": 36,
    "2025-12-31": 34,
    "2026-01-01": 7,
    "2026-01-02": 35
  }
}
```

---

### GET /releases/{fred_release_id}

Get a specific FRED release by its FRED release ID.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `fred_release_id` | int | FRED release ID |

**Response:**
```json
{
  "id": 1,
  "fred_release_id": 10,
  "name": "Consumer Price Index",
  "link": "https://www.bls.gov/cpi/",
  "press_release": true
}
```

---

### GET /releases/{fred_release_id}/schedule

Get a release and its upcoming schedule.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `fred_release_id` | int | FRED release ID |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 90 | Days ahead (1-365) |

**Response:**
```json
{
  "fred_release_id": 10,
  "name": "Consumer Price Index",
  "link": "https://www.bls.gov/cpi/",
  "notes": "The Consumer Price Index (CPI) measures...",
  "press_release": true,
  "upcoming_dates": ["2026-01-10", "2026-02-12", "2026-03-12"],
  "next_release": "2026-01-10"
}
```

---

### GET /releases/{fred_release_id}/dates

Get upcoming release dates for a specific FRED release.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `fred_release_id` | int | FRED release ID |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | int | 90 | Days ahead (1-365) |

**Response:**
```json
[
  {"release_date": "2026-01-10"},
  {"release_date": "2026-02-12"},
  {"release_date": "2026-03-12"}
]
```

---

### POST /releases/sync

Sync FRED releases and upcoming release dates from the FRED API.
Requires `X-Scrivener-API-Key` matching the configured `SCRIVENER_API_KEY`.
The response indicates whether the fetched snapshot was `complete` enough to reconcile destructively or whether Scrivener stayed in degraded, insert-only mode.
Degraded syncs return HTTP `503` with the sync payload in the error detail.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days_ahead` | int | 90 | Days ahead to sync (1-365) |

**Response:**
```json
{
  "status": "complete",
  "ready": true,
  "releases": {
    "fetched": 321,
    "expected": 321,
    "inserted": 321,
    "updated": 0,
    "complete": true,
    "status": "complete",
    "degraded_reason": null
  },
  "dates": {
    "fetched": 764,
    "expected": 764,
    "inserted": 764,
    "skipped": 0,
    "skipped_missing_release": 0,
    "removed": 12,
    "complete": true,
    "status": "complete",
    "degraded_reason": null,
    "destructive_cleanup_performed": true,
    "integrity_ok": true,
    "anchor_validation": {
      "enabled": true,
      "ok": true,
      "checked_until": "2026-05-18",
      "missing_releases": []
    }
  }
}
```

---

## Error Responses

All endpoints return standard HTTP error codes:

| Code | Description |
|------|-------------|
| 200 | Success |
| 404 | Resource not found |
| 422 | Validation error (invalid parameters) |
| 500 | Internal server error |

**Error Response Format:**
```json
{
  "detail": "Series 'INVALID' not found"
}
```

---

## Usage Examples

### Python (requests)

```python
import requests

BASE_URL = "http://localhost:8000"

# Get latest Fed Funds rate
resp = requests.get(f"{BASE_URL}/series/FEDFUNDS/latest")
print(resp.json())
# {"series_id": "FEDFUNDS", "date": "2025-11-01", "value": 3.88}

# Get multiple series at once
resp = requests.post(
    f"{BASE_URL}/series/batch/latest",
    json=["GDP", "UNRATE", "CPIAUCSL"]
)
print(resp.json())

# Get recent Powell speeches
resp = requests.get(
    f"{BASE_URL}/speeches/speaker/Powell",
    params={"limit": 5}
)
print(resp.json())

# Get auction summary
resp = requests.get(
    f"{BASE_URL}/auctions/summary",
    params={"days": 30, "security_type": "Note"}
)
print(resp.json())
```

### cURL

```bash
# Health check
curl http://localhost:8000/health

# Get latest value
curl "http://localhost:8000/series/FEDFUNDS/latest"

# Get observations with date range
curl "http://localhost:8000/series/GDP/observations?start_date=2024-01-01&end_date=2025-01-01"

# List speeches
curl "http://localhost:8000/speeches?speaker=Jefferson&days=90"

# Get speech by URL
curl "http://localhost:8000/speeches/by-url?url=https://www.federalreserve.gov/newsevents/speech/jefferson20251107a.htm"
```

---

## Rate Limits

This API is designed for internal service-to-service communication. No rate limits are enforced.

For production deployments, consider adding rate limiting via a reverse proxy (nginx, Caddy) or API gateway.
