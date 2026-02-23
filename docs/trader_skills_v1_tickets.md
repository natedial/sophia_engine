# Trader Skills V1 Tickets

## Purpose

Execution-ready backlog for:

1. Catalyst Radar
2. Trade Idea Generator
3. Position-Aware Risk Lens

Reference spec: `docs/trader_skills_v1_spec.md`

## Planning Assumptions

- Team can ship backend + frontend in parallel.
- V1 uses deterministic scoring with optional LLM narrative layer.
- V1 position input is request payload + CSV upload (no OMS live pull).
- Persistence lives in a new Postgres schema `trader_assistant`.

Estimate scale:

- `S`: 0.5-1 day
- `M`: 1-2 days
- `L`: 2-4 days

## Critical Path

1. Data schema + gateway contracts
2. Catalyst ingestion + scoring
3. Trade idea generator + scoring
4. Risk exposure engine + event shock engine
5. UI cards + E2E QA

## Sprint Cut Recommendation

### Week 1 (must ship)

- BE-01 to BE-08
- DATA-01 to DATA-04
- QA-01, QA-02

### Week 2 (finish + harden)

- BE-09 to BE-13
- FE-01 to FE-06
- QA-03 to QA-06

## Ticket Index

- Backend: BE-01..BE-13
- Data: DATA-01..DATA-04
- Frontend: FE-01..FE-06
- QA/Observability: QA-01..QA-06

---

## Backend Tickets

### BE-01 Gateway Skill API Models

- Objective: Add typed request/response models for all three skill endpoints.
- Scope:
- New Pydantic models for Catalyst Radar, Trade Ideas, Risk Lens.
- Validation for required risk controls (`invalidation`, `stop`, NAV > 0).
- Out of scope: scoring logic.
- File targets:
- `agents/sophia_prima/src/sophia/gateway/app.py`
- `agents/sophia_prima/src/sophia/gateway/models.py`
- `agents/sophia_prima/src/sophia/gateway/__init__.py`
- Dependencies: none.
- Estimate: `S`
- Acceptance criteria:
- Endpoints compile with model validation.
- Invalid payloads return `400` with actionable detail.
- Tests:
- Add model validation tests in `agents/sophia_prima/tests/test_gateway_skill_models.py`.

### BE-02 Skill Service Module Skeleton

- Objective: Establish service layer (separate from HTTP routes).
- Scope:
- Create service modules for `catalyst_radar`, `trade_ideas`, `risk_lens`.
- Define shared interfaces and result envelopes.
- Out of scope: persistence, scoring internals.
- File targets:
- `agents/sophia_prima/src/sophia/skills/__init__.py` (new)
- `agents/sophia_prima/src/sophia/skills/catalyst_radar.py` (new)
- `agents/sophia_prima/src/sophia/skills/trade_ideas.py` (new)
- `agents/sophia_prima/src/sophia/skills/risk_lens.py` (new)
- Dependencies: BE-01.
- Estimate: `M`
- Acceptance criteria:
- Routes call service methods, not inline logic.
- Tests:
- Add unit tests for service stubs in `agents/sophia_prima/tests/test_skill_service_skeleton.py`.

### BE-03 Pylon Event Adapter (Scrivener Ingestion)

- Objective: Normalize releases/speeches/auctions into a common catalyst event shape.
- Scope:
- Adapter functions wrapping existing pylon tools:
- `get_releases_upcoming`
- `get_releases_week`
- `get_speeches`
- `get_auctions`
- Event identity format: `type:id:date`.
- Out of scope: event scoring.
- File targets:
- `agents/sophia_prima/src/sophia/skills/catalyst_radar.py`
- `services/sophia_pylon/src/pylon/tools/scrivener.py` (only if missing metadata fields)
- Dependencies: BE-02.
- Estimate: `M`
- Acceptance criteria:
- Given fixed tool payloads, normalized events are deterministic and stable.
- Tests:
- `agents/sophia_prima/tests/test_catalyst_event_adapter.py`.

### BE-04 Catalyst Radar Deterministic Scoring

- Objective: Implement impact scoring formula and buckets from spec.
- Scope:
- Component scores: `event_importance`, `surprise_risk`, `positioning_risk`, `cross_asset_sensitivity`, `time_proximity`.
- Weighted score and bucket mapping.
- Out of scope: LLM narrative.
- File targets:
- `agents/sophia_prima/src/sophia/skills/catalyst_radar.py`
- `agents/sophia_prima/src/sophia/skills/scoring.py` (new)
- Dependencies: BE-03.
- Estimate: `L`
- Acceptance criteria:
- Score output is reproducible for same input.
- Buckets match threshold definitions.
- Tests:
- `agents/sophia_prima/tests/test_catalyst_scoring.py`.

### BE-05 Catalyst Radar API Endpoint

- Objective: Expose `POST /v1/skills/catalyst-radar/run`.
- Scope:
- Wire endpoint in gateway app.
- Return ranked events + summary payload.
- Out of scope: persistence.
- File targets:
- `agents/sophia_prima/src/sophia/gateway/app.py`
- `agents/sophia_prima/src/sophia/gateway/runtime.py` (if orchestration state needed)
- Dependencies: BE-01, BE-04.
- Estimate: `S`
- Acceptance criteria:
- Endpoint returns sorted events by `impact_score`.
- Proper handling when upstream tools unavailable.
- Tests:
- `agents/sophia_prima/tests/test_catalyst_radar_endpoint.py`.

### BE-06 Trade Idea Template Engine

- Objective: Deterministic generation of trade idea cards from catalysts.
- Scope:
- Build structured card with required fields:
- `thesis`, `expression`, `entry_zone`, `invalidation`, `target`, `stop`, `kill_criteria`.
- Enforce fail-close if required risk controls missing.
- Out of scope: portfolio-aware penalties.
- File targets:
- `agents/sophia_prima/src/sophia/skills/trade_ideas.py`
- Dependencies: BE-04.
- Estimate: `L`
- Acceptance criteria:
- Every emitted idea has full risk framing.
- No cards emitted when constraints are violated.
- Tests:
- `agents/sophia_prima/tests/test_trade_idea_template_engine.py`.

### BE-07 Trade Idea Scoring

- Objective: Implement quality/confidence scoring formula from spec.
- Scope:
- `quality_score` and `confidence_score`.
- Confidence incorporates data completeness.
- Out of scope: persistence.
- File targets:
- `agents/sophia_prima/src/sophia/skills/trade_ideas.py`
- `agents/sophia_prima/src/sophia/skills/scoring.py`
- Dependencies: BE-06.
- Estimate: `M`
- Acceptance criteria:
- Scores are deterministic and clipped to `[0,100]`.
- Tests:
- `agents/sophia_prima/tests/test_trade_idea_scoring.py`.

### BE-08 Trade Idea API Endpoint

- Objective: Expose `POST /v1/skills/trade-ideas/generate`.
- Scope:
- Request validation + response formatting.
- Optional `max_ideas` and `style` handling.
- Out of scope: persistence.
- File targets:
- `agents/sophia_prima/src/sophia/gateway/app.py`
- Dependencies: BE-01, BE-07.
- Estimate: `S`
- Acceptance criteria:
- Endpoint returns 0..N ideas with required fields.
- Tests:
- `agents/sophia_prima/tests/test_trade_ideas_endpoint.py`.

### BE-09 Risk Lens Exposure Engine

- Objective: Compute factor exposures from positions + mapping table.
- Scope:
- Convert position list into net/gross factor exposures.
- Factor concentration (`HHI`) computation.
- Out of scope: event scenario shocks.
- File targets:
- `agents/sophia_prima/src/sophia/skills/risk_lens.py`
- `agents/sophia_prima/src/sophia/skills/factor_mapping.py` (new)
- Dependencies: BE-02, DATA-03.
- Estimate: `L`
- Acceptance criteria:
- Exposure and concentration values are reproducible.
- Unknown symbols are surfaced explicitly.
- Tests:
- `agents/sophia_prima/tests/test_risk_exposure_engine.py`.

### BE-10 Event Shock Engine

- Objective: Estimate event-at-risk PnL by scenario.
- Scope:
- Scenario templates (`hot_cpi`, `soft_cpi`, `hawkish_fed`, `dovish_fed`).
- Compute estimated `pnl_bps_nav` per scenario.
- Out of scope: stochastic simulation.
- File targets:
- `agents/sophia_prima/src/sophia/skills/risk_lens.py`
- `agents/sophia_prima/src/sophia/skills/scenarios.py` (new)
- Dependencies: BE-09, BE-05.
- Estimate: `M`
- Acceptance criteria:
- Scenario PnL output exists for each relevant upcoming event.
- Tests:
- `agents/sophia_prima/tests/test_event_shock_engine.py`.

### BE-11 Risk Lens Scoring + Hidden Risks

- Objective: Produce summary scores and hidden risk bullets.
- Scope:
- `overall_risk_score`, concentration, event risk, cluster risk, liquidity stress.
- Rule-based hidden risk generation.
- Out of scope: LLM prose polishing.
- File targets:
- `agents/sophia_prima/src/sophia/skills/risk_lens.py`
- Dependencies: BE-10.
- Estimate: `M`
- Acceptance criteria:
- Summary scores within expected ranges, hidden risk bullets present.
- Tests:
- `agents/sophia_prima/tests/test_risk_lens_scoring.py`.

### BE-12 Risk Lens API Endpoint

- Objective: Expose `POST /v1/skills/risk-lens/analyze`.
- Scope:
- Accept positions payload and optional catalyst IDs.
- Return score summary + exposures + event-at-risk.
- Out of scope: async job orchestration.
- File targets:
- `agents/sophia_prima/src/sophia/gateway/app.py`
- Dependencies: BE-01, BE-11.
- Estimate: `S`
- Acceptance criteria:
- Endpoint returns stable output with explainable components.
- Tests:
- `agents/sophia_prima/tests/test_risk_lens_endpoint.py`.

### BE-13 Skill Endpoint Routing Through WebSocket

- Objective: Allow dashboard WS clients to request skill runs.
- Scope:
- Add WS frame types for skill requests/responses.
- Backward-compatible with existing `inbound_message`.
- Out of scope: frontend wiring.
- File targets:
- `agents/sophia_prima/src/sophia/gateway/app.py`
- `frontend/sophia-dashboard/src/types/websocket.ts`
- Dependencies: BE-05, BE-08, BE-12.
- Estimate: `M`
- Acceptance criteria:
- WS clients can execute each skill and receive typed response frames.
- Tests:
- `agents/sophia_prima/tests/test_gateway_ws_skill_frames.py`.

---

## Data Tickets

### DATA-01 Create Trader Assistant Schema Migration

- Objective: Add V1 persistence schema/tables.
- Scope:
- Create tables from spec:
- `portfolio_positions`, `factor_mappings`, `catalyst_events`, `catalyst_scores`, `trade_idea_cards`, `trade_idea_links`, `risk_snapshots`, `risk_factor_exposures`, `event_risk_contributions`.
- Add primary keys + indexes.
- Out of scope: data backfill.
- File targets:
- `infra/migrations/` (new folder + SQL migration files)
- `docs/trader_skills_v1_spec.md` (if schema doc updates needed)
- Dependencies: none.
- Estimate: `L`
- Acceptance criteria:
- Migration applies cleanly up/down in local dev.
- Tests:
- SQL smoke script in `infra/migrations/README.md` (new).

### DATA-02 Persistence Repository Layer

- Objective: Abstract reads/writes for skill artifacts.
- Scope:
- Implement repository module for writing score snapshots and cards.
- Out of scope: caching.
- File targets:
- `agents/sophia_prima/src/sophia/skills/repository.py` (new)
- `agents/sophia_prima/src/sophia/config.py` (DB settings for trader_assistant)
- Dependencies: DATA-01, BE-02.
- Estimate: `M`
- Acceptance criteria:
- Endpoints can persist and retrieve latest snapshots.
- Tests:
- `agents/sophia_prima/tests/test_skills_repository.py`.

### DATA-03 Seed Factor Mappings

- Objective: Provide initial symbol->factor beta map for core macro book.
- Scope:
- Seed mappings for common rates, FX, equity index symbols.
- Out of scope: dynamic beta estimation.
- File targets:
- `infra/seeds/factor_mappings_v1.csv` (new)
- `agents/sophia_prima/src/sophia/skills/factor_mapping.py`
- Dependencies: DATA-01.
- Estimate: `S`
- Acceptance criteria:
- Risk lens can resolve factors for initial supported symbols.
- Tests:
- `agents/sophia_prima/tests/test_factor_mapping_seed.py`.

### DATA-04 CSV Position Ingestion Parser

- Objective: Parse PM upload format into normalized position objects.
- Scope:
- CSV parser with schema validation and error reporting.
- Out of scope: broker-specific adapters.
- File targets:
- `agents/sophia_prima/src/sophia/skills/position_ingest.py` (new)
- Dependencies: BE-09.
- Estimate: `M`
- Acceptance criteria:
- Valid CSV parses to normalized payload; bad rows return actionable errors.
- Tests:
- `agents/sophia_prima/tests/test_position_csv_ingest.py`.

---

## Frontend Tickets

### FE-01 API Client Methods for Skill Endpoints

- Objective: Add typed client calls for all three endpoints.
- Scope:
- HTTP methods + TypeScript interfaces.
- Out of scope: UI rendering.
- File targets:
- `frontend/sophia-dashboard/src/services/api.ts`
- `frontend/sophia-dashboard/src/types/websocket.ts`
- Dependencies: BE-05, BE-08, BE-12.
- Estimate: `S`
- Acceptance criteria:
- API methods compile and return typed responses.

### FE-02 Catalyst Radar Card

- Objective: Render ranked catalysts and details.
- Scope:
- Top list, impact badges, detail drawer, 24h/72h filter.
- Out of scope: chart overlays.
- File targets:
- `frontend/sophia-dashboard/src/components/Skills/CatalystRadarCard.tsx` (new)
- `frontend/sophia-dashboard/src/store/canvasStore.ts` (if store integration needed)
- `frontend/sophia-dashboard/src/styles/App.css`
- Dependencies: FE-01.
- Estimate: `M`
- Acceptance criteria:
- Users can run radar and inspect top events with scores.

### FE-03 Trade Ideas Card

- Objective: Render idea cards with controls.
- Scope:
- Show entry/target/stop/invalidation, quality/confidence.
- Actions: accept/reject/snooze.
- Out of scope: broker ticket export.
- File targets:
- `frontend/sophia-dashboard/src/components/Skills/TradeIdeasCard.tsx` (new)
- `frontend/sophia-dashboard/src/store/canvasStore.ts`
- Dependencies: FE-01.
- Estimate: `M`
- Acceptance criteria:
- Cards render all required fields and action handlers fire.

### FE-04 Risk Lens Card

- Objective: Render risk summary, factor exposures, event-at-risk table.
- Scope:
- Summary gauges and tables.
- Scenario toggle.
- Out of scope: real-time streaming updates.
- File targets:
- `frontend/sophia-dashboard/src/components/Skills/RiskLensCard.tsx` (new)
- `frontend/sophia-dashboard/src/components/Charts/VegaChart.tsx` (optional exposure charts)
- Dependencies: FE-01.
- Estimate: `M`
- Acceptance criteria:
- Card displays exposures and event scenarios from API response.

### FE-05 Positions Upload UX

- Objective: Add CSV upload and preview for risk lens input.
- Scope:
- Upload, preview, row-level validation messages.
- Out of scope: persistent file storage.
- File targets:
- `frontend/sophia-dashboard/src/components/Skills/PositionUpload.tsx` (new)
- `frontend/sophia-dashboard/src/services/api.ts`
- Dependencies: DATA-04, FE-04.
- Estimate: `M`
- Acceptance criteria:
- User can upload valid CSV and run risk lens in one flow.

### FE-06 Dashboard Integration and Navigation

- Objective: Add skills module entry point in existing dashboard.
- Scope:
- Mount skill cards and state orchestration.
- Out of scope: mobile redesign.
- File targets:
- `frontend/sophia-dashboard/src/App.tsx`
- `frontend/sophia-dashboard/src/components/Layout/Header.tsx`
- Dependencies: FE-02, FE-03, FE-04.
- Estimate: `S`
- Acceptance criteria:
- User can navigate and execute all three skills from dashboard.

---

## QA and Observability Tickets

### QA-01 Endpoint Contract Tests

- Objective: Validate request/response contracts for skill endpoints.
- Scope:
- Positive/negative API tests.
- Out of scope: load testing.
- File targets:
- `agents/sophia_prima/tests/test_skill_endpoint_contracts.py` (new)
- Dependencies: BE-05, BE-08, BE-12.
- Estimate: `S`
- Acceptance criteria:
- Contracts match spec shapes and validations.

### QA-02 Determinism Regression Tests

- Objective: Ensure deterministic scoring outputs remain stable.
- Scope:
- Snapshot-style fixtures for scoring modules.
- Out of scope: model drift checks.
- File targets:
- `agents/sophia_prima/tests/test_skill_scoring_snapshots.py` (new)
- Dependencies: BE-04, BE-07, BE-11.
- Estimate: `S`
- Acceptance criteria:
- Same input fixture => same score output.

### QA-03 Gateway/Pylon Integration Tests

- Objective: Validate end-to-end tool orchestration against local services.
- Scope:
- Integration path for catalysts and risk scenarios.
- Out of scope: staging environments.
- File targets:
- `agents/sophia_prima/tests/test_skill_gateway_integration.py` (new)
- Dependencies: BE-03, BE-05, BE-08, BE-12.
- Estimate: `M`
- Acceptance criteria:
- Skills run successfully with local `infra` stack.

### QA-04 Frontend Interaction Tests

- Objective: Verify skill card interactions and state updates.
- Scope:
- Component tests for run actions, filters, error states.
- Out of scope: visual regression baseline.
- File targets:
- `frontend/sophia-dashboard/src/components/Skills/__tests__/` (new)
- Dependencies: FE-02..FE-06.
- Estimate: `M`
- Acceptance criteria:
- Core user flows pass with mocked API responses.

### QA-05 Metrics and Logging

- Objective: Add structured logs and key metrics for skills.
- Scope:
- Emit latency, result counts, error class, score distribution summary.
- Out of scope: full tracing rollout.
- File targets:
- `agents/sophia_prima/src/sophia/gateway/app.py`
- `agents/sophia_prima/src/sophia/skills/*.py`
- Dependencies: BE-05, BE-08, BE-12.
- Estimate: `S`
- Acceptance criteria:
- Logs include request id and skill id; metrics visible in local logs.

### QA-06 UAT Script (Morning Prep + Intraday)

- Objective: Codify PM validation workflow for real usage.
- Scope:
- Morning prep runbook: Radar -> Ideas -> Risk Lens.
- Intraday refresh runbook with scenario update.
- Out of scope: training docs.
- File targets:
- `docs/trader_skills_v1_uat.md` (new)
- Dependencies: all FE and BE done.
- Estimate: `S`
- Acceptance criteria:
- Human UAT can execute script and record pass/fail per step.

---

## Dependency Matrix (Condensed)

- BE-01 -> BE-02 -> BE-03 -> BE-04 -> BE-05
- BE-04 -> BE-06 -> BE-07 -> BE-08
- DATA-01 -> DATA-02 -> BE-05/BE-08/BE-12 persistence wiring
- DATA-03 + BE-09 -> BE-10 -> BE-11 -> BE-12
- BE-05/08/12 -> FE-01 -> FE-02/03/04 -> FE-05/06
- Core BE complete -> QA-01/02/03 -> FE complete -> QA-04/06

## Suggested Owners

- Backend lead: BE-01..BE-13
- Data/platform: DATA-01..DATA-04
- Frontend lead: FE-01..FE-06
- QA lead: QA-01..QA-06

## Risks To Monitor

1. Position data quality can block meaningful risk outputs.
2. Factor mapping coverage may be thin for less common symbols.
3. Overly complex scoring can reduce explainability; keep formulas transparent.
4. Upstream Scrivener data gaps can weaken Catalyst Radar confidence.
