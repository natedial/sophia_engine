# Trader Skills V1 Spec

## Scope

This spec defines V1 for three skills:

1. Catalyst Radar (Skill 2)
2. Trade Idea Generator (Skill 4)
3. Position-Aware Risk Lens (Skill 5)

Design goals:

- High daily utility for morning prep and intraday refresh.
- Deterministic core scoring first, LLM used for synthesis and explanation.
- Reuse existing Sophia stack (`sophia_gateway`, `sophia_pylon`, `scrivener`, `arithmos`, `canvas`).

Non-goals for V1:

- Full OMS integration.
- Real-time tick-by-tick risk.
- Automated execution.

## Architecture Fit

Execution path:

1. Client calls `sophia_gateway` skill endpoint.
2. Gateway orchestrates deterministic calculations + `pylon` tool calls.
3. Gateway persists artifacts to Postgres.
4. Gateway returns structured payload plus optional narrative summary.
5. Dashboard renders cards and optional charts.

Data sources in V1:

- Releases: `get_releases_upcoming`, `get_releases_week`, `get_releases_summary`
- Speeches: `get_speeches`, `get_speech`
- Auctions: `get_auctions`, `get_auction_summary`
- Series context: `get_latest_value`, `get_observations`, `get_series_change`
- Compute helper: `compute`

## API Contracts

All endpoints are proposed under `sophia_gateway`.

### 1) Catalyst Radar

`POST /v1/skills/catalyst-radar/run`

Request:

```json
{
  "window_hours": 72,
  "portfolio_profile": {
    "focus_assets": ["rates", "usd", "equities"],
    "regions": ["US", "EU"]
  },
  "include": {
    "economic_releases": true,
    "central_bank_speeches": true,
    "auctions": true
  },
  "max_events": 25,
  "as_of": "2026-02-23T13:30:00Z"
}
```

Response:

```json
{
  "as_of": "2026-02-23T13:30:00Z",
  "window_hours": 72,
  "events": [
    {
      "event_id": "release:10:2026-02-24",
      "event_type": "economic_release",
      "name": "Consumer Price Index",
      "scheduled_at": "2026-02-24T13:30:00Z",
      "impact_score": 86.4,
      "impact_bucket": "high",
      "surprise_risk_score": 72.0,
      "positioning_risk_score": 64.5,
      "affected_assets": ["US2Y", "US10Y", "DXY", "SPX"],
      "watch_levels": [
        {"asset": "US10Y", "level": 4.35, "direction": "break_above"},
        {"asset": "DXY", "level": 105.20, "direction": "break_below"}
      ],
      "base_case": "Inline print; limited follow-through.",
      "upside_case": "Hot print; front-end reprices higher.",
      "downside_case": "Soft print; bull steepening."
    }
  ],
  "top_three_summary": [
    "CPI likely to drive front-end rates and USD in the next session.",
    "Auction tail risk elevated for intermediate tenors.",
    "Fed speaker cluster may reinforce policy path uncertainty."
  ]
}
```

### 2) Trade Idea Generator

`POST /v1/skills/trade-ideas/generate`

Request:

```json
{
  "horizon": "intraday",
  "risk_budget_bps": 35,
  "max_ideas": 5,
  "catalyst_ids": ["release:10:2026-02-24", "speech:powell:2026-02-24"],
  "portfolio_constraints": {
    "no_new_em_fx": true,
    "max_gross_leverage": 3.0
  },
  "style": "macro_relative_value"
}
```

Response:

```json
{
  "as_of": "2026-02-23T13:35:00Z",
  "ideas": [
    {
      "idea_id": "idea_20260223_001",
      "title": "Receive 2y vs Pay 10y into softer CPI path",
      "thesis": "Disinflation surprise risks exceed current front-end pricing.",
      "expression": "2s10s bull steepener via swaps",
      "entry_zone": "2s10s <= -34 bps",
      "invalidation": "CPI core MoM >= 0.4 or 2y breaks prior high",
      "target": "2s10s to -20 bps",
      "stop": "2s10s to -42 bps",
      "expected_holding_period_days": 3,
      "catalyst_path": ["CPI", "Fed speaker tone"],
      "risk_reward_ratio": 2.2,
      "confidence_score": 74.0,
      "quality_score": 78.5,
      "kill_criteria": [
        "No post-data follow-through within 2 hours",
        "USD broad strength regime shift persists"
      ]
    }
  ]
}
```

### 3) Position-Aware Risk Lens

`POST /v1/skills/risk-lens/analyze`

Request:

```json
{
  "portfolio_id": "pm_main",
  "positions": [
    {
      "symbol": "US10Y_FUT",
      "asset_class": "rates",
      "direction": "long",
      "notional_usd": 12000000
    },
    {
      "symbol": "DXY_FUT",
      "asset_class": "fx",
      "direction": "short",
      "notional_usd": 5000000
    }
  ],
  "upcoming_catalyst_ids": ["release:10:2026-02-24"],
  "nav_usd": 150000000
}
```

Response:

```json
{
  "portfolio_id": "pm_main",
  "as_of": "2026-02-23T13:36:30Z",
  "risk_summary": {
    "overall_risk_score": 68.2,
    "factor_concentration_score": 71.4,
    "event_risk_score": 65.0,
    "liquidity_stress_score": 40.3
  },
  "factor_exposures": [
    {"factor": "usd_level", "net_beta_usd": -4200000},
    {"factor": "rates_level", "net_beta_usd": 7800000},
    {"factor": "curve_2s10s", "net_beta_usd": 2300000}
  ],
  "event_at_risk": [
    {
      "event_id": "release:10:2026-02-24",
      "scenario": "hot_cpi",
      "estimated_pnl_bps_nav": -19.5
    }
  ],
  "top_hidden_risks": [
    "Short USD and long duration exposures are negatively convex to hot CPI.",
    "Concentration in two macro factors exceeds policy threshold.",
    "Stop distances overlap, increasing gap risk around release timestamp."
  ]
}
```

## Deterministic Scoring Formulas

All scores are `0-100` and clipped to `[0, 100]`.

### A) Catalyst Radar Score

`impact_score = 0.35*event_importance + 0.25*surprise_risk + 0.20*positioning_risk + 0.10*cross_asset_sensitivity + 0.10*time_proximity`

Definitions:

- `event_importance`: fixed lookup by event class (CPI, NFP, FOMC, auctions, key speeches).
- `surprise_risk`: rolling z-score of forecast dispersion and recent miss magnitude.
- `positioning_risk`: proxy from recent trend extension + crowded-direction signals.
- `cross_asset_sensitivity`: number and beta-weight of impacted assets.
- `time_proximity`: decays linearly to zero at end of selected window.

Bucket mapping:

- `>= 75`: high
- `50-74.99`: medium
- `< 50`: low

### B) Trade Idea Quality Score

`quality_score = 0.30*edge_strength + 0.20*catalyst_clarity + 0.20*risk_reward + 0.15*regime_alignment + 0.10*execution_feasibility + 0.05*portfolio_fit`

Where:

- `risk_reward = min(100, 25 * R_multiple)` where `R_multiple = expected_reward / expected_risk`.
- `portfolio_fit` penalizes ideas that increase already concentrated factor exposures.
- Hard fail if no explicit invalidation or stop.

Confidence:

`confidence_score = 0.6*quality_score + 0.4*data_completeness_score`

### C) Risk Lens Score

`overall_risk_score = 0.40*factor_concentration + 0.35*event_risk + 0.15*correlation_cluster_risk + 0.10*liquidity_stress`

Factor concentration:

1. Compute absolute factor exposure weights `w_f = |exposure_f| / sum(|exposure|)`.
2. `hhi = sum(w_f^2)`.
3. `factor_concentration = 100 * ((hhi - hhi_min) / (1 - hhi_min))`, with `hhi_min = 1/N`.

Event risk:

- For each upcoming event/scenario:
  - `scenario_pnl = sum(position_notional * factor_beta * scenario_shock)`
- `event_risk_score` scales worst-case near-window scenario to score bands by bps of NAV.

## Data Model (Postgres)

Use schema: `trader_assistant`.

### Core tables

1. `portfolio_positions`
- `id`, `portfolio_id`, `as_of`, `symbol`, `asset_class`, `direction`, `notional_usd`, `source`
- Index: `(portfolio_id, as_of desc)`

2. `factor_mappings`
- `symbol`, `factor_name`, `beta`, `updated_at`
- PK: `(symbol, factor_name)`

3. `catalyst_events`
- `event_id`, `event_type`, `name`, `scheduled_at`, `region`, `raw_payload`
- Index: `(scheduled_at, event_type)`

4. `catalyst_scores`
- `event_id`, `as_of`, component scores, `impact_score`, `impact_bucket`
- PK: `(event_id, as_of)`

5. `trade_idea_cards`
- `idea_id`, `as_of`, `title`, `thesis`, `expression`, `entry_zone`, `invalidation`, `target`, `stop`, `quality_score`, `confidence_score`, `status`
- Index: `(as_of desc, status)`

6. `trade_idea_links`
- `idea_id`, `event_id`, `portfolio_id`

7. `risk_snapshots`
- `snapshot_id`, `portfolio_id`, `as_of`, summary scores, `nav_usd`
- Index: `(portfolio_id, as_of desc)`

8. `risk_factor_exposures`
- `snapshot_id`, `factor_name`, `net_beta_usd`, `gross_beta_usd`

9. `event_risk_contributions`
- `snapshot_id`, `event_id`, `scenario_name`, `estimated_pnl_bps_nav`

### Optional journal-ready extension (future-compatible)

10. `trade_outcomes`
- `idea_id`, `opened_at`, `closed_at`, `realized_pnl_bps`, `outcome_label`, `post_mortem`

## UI Cards (Dashboard)

### 1) Catalyst Radar Card

Sections:

- Top 3 catalysts (impact badges).
- Timeline view (next 24h/72h).
- Event detail drawer: impacted assets, watch levels, scenario text.

Interactions:

- Filter by region/asset class.
- "Generate ideas from selected catalysts" action.

### 2) Trade Ideas Card

Per-idea fields:

- Title, expression, quality/confidence.
- Entry, target, stop, invalidation.
- Catalyst tags and expected hold window.

Interactions:

- Accept/Reject/Snooze.
- Convert to journal draft.
- Push selected idea into risk lens "what-if".

### 3) Risk Lens Card

Sections:

- Risk summary gauges.
- Factor exposure bars.
- Event-at-risk table (scenario, estimated PnL bps NAV).
- Hidden risk bullets.

Interactions:

- Upload/refresh positions.
- Scenario toggle (base/hot/soft).
- Drill down by factor and symbol.

## Implementation Plan (2 Weeks)

### Week 1

Day 1:

- Finalize payload schemas and OpenAPI contracts.
- Create DB migration for `trader_assistant` schema.

Day 2:

- Implement `catalyst_events` ingestion adapter from Scrivener endpoints.
- Implement deterministic Catalyst Radar scoring module.

Day 3:

- Implement `POST /v1/skills/catalyst-radar/run`.
- Persist `catalyst_scores` and return ranked events.

Day 4:

- Implement Trade Idea template engine (deterministic skeleton generation).
- Add quality and confidence scoring functions.

Day 5:

- Implement `POST /v1/skills/trade-ideas/generate`.
- Persist `trade_idea_cards` and `trade_idea_links`.

### Week 2

Day 6:

- Implement position ingestion path in Risk Lens endpoint (payload and CSV parser).
- Create factor mapping registry with seed mappings for core symbols.

Day 7:

- Implement exposure engine and concentration scoring.
- Implement event shock engine for top catalyst scenarios.

Day 8:

- Implement `POST /v1/skills/risk-lens/analyze`.
- Persist `risk_snapshots`, `risk_factor_exposures`, `event_risk_contributions`.

Day 9:

- Dashboard cards: Catalyst Radar, Trade Ideas, Risk Lens.
- Add actions (generate from catalyst, what-if from idea).

Day 10:

- End-to-end QA and regression tests.
- Dry-run with one PM workflow (morning prep + one intraday refresh).
- Tune scoring thresholds and finalize defaults.

## Acceptance Criteria

Catalyst Radar:

- Returns ranked events with stable deterministic scores.
- Top 10 response time under 2 seconds excluding upstream API latency.

Trade Idea Generator:

- Every idea includes entry, invalidation, stop, target, and kill criteria.
- No idea emitted when required risk controls are missing.

Risk Lens:

- Produces reproducible factor exposures for same input snapshot.
- Flags top hidden risks and event-at-risk scenarios with explainable components.

## Open Questions

1. Source of truth for positions in V1: CSV upload only, or direct broker/OMS pull?
2. NAV source: user-provided per request, or stored portfolio profile?
3. Preferred factor taxonomy: lean (5-8 factors) or richer (15+ factors) at launch?
4. Should accepted trade ideas auto-create journal entries in V1 or V1.1?
