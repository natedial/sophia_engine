# Sophia Kampe

Financial model management service for the Sophia ecosystem.

## Overview

Sophia Kampe (καμπή = curve) manages the lifecycle of financial models—curves, surfaces, and more:
- **Yield Curves**: Nelson-Siegel, Svensson, splines, zero curves, forward curves
- **Volatility Surfaces**: SABR, SVI, local vol, implied vol
- **Credit Curves**: Hazard rates, credit spreads, survival probabilities

For each model type:
- Fit models to market data
- Apply and refine constraints
- Manage state (pending → fitted → published)
- Interpolate/evaluate at arbitrary points
- Version and track history

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  sophia_pylon   │────▶│  sophia_kampe   │     │ sophia_arithmos │
│  (gateway)      │     │  (model mgmt)   │     │  (stats/econ)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                         • Curves                 • Transformations
                         • Vol surfaces           • Regression
                         • Credit models          • Descriptive stats
                         • Fitting + lifecycle
```

## Status

**This is a scaffold.** The API structure and model framework are defined,
but the actual model implementations are not yet built.

### What's Implemented
- Project structure and configuration
- Generic `Model` type (supports curves, vol surfaces, credit)
- In-memory model store with type/date indexing
- API endpoints (returning 501 for unimplemented operations)
- Base class for financial models

### What's Planned
- **Curves**: Nelson-Siegel, Svensson, splines, bootstrap
- **Volatility**: SABR, SVI, local vol
- **Credit**: Hazard curves, spread curves
- Constraint application and refinement
- Model evaluation/interpolation
- History and versioning
- Optional persistence backend

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running

```bash
# Ensure Arithmos is running on port 8001
cp .env.example .env
python -m sophia_kampe.main
```

Server runs on port 8002 by default.

## API Endpoints

| Endpoint | Method | Description | Status |
|----------|--------|-------------|--------|
| `/health` | GET | Health check | ✅ |
| `/curves` | GET | List all curves | ✅ |
| `/curves/{id}` | GET | Get curve by ID | ✅ |
| `/curves` | POST | Fit new curve | 🚧 Scaffold |
| `/curves/{id}/refine` | POST | Refine with constraints | 🚧 Scaffold |
| `/curves/{id}/publish` | POST | Publish curve | 🚧 Scaffold |
| `/curves/interpolate` | POST | Interpolate yields | 🚧 Scaffold |
| `/curves/{id}` | DELETE | Delete curve | ✅ |

## Model Lifecycle

```
    ┌─────────┐
    │ PENDING │  Initial state after creation
    └────┬────┘
         │ fit()
         ▼
    ┌─────────┐
    │ FITTED  │  Parameters computed
    └────┬────┘
         │ refine() [optional, repeatable]
         ▼
    ┌──────────┐
    │ REFINING │  Applying constraints
    └────┬─────┘
         │ publish()
         ▼
    ┌───────────┐
    │ PUBLISHED │  Ready for consumption
    └───────────┘
```

## Model Types

### Yield Curves
| Type | Parameters | Use Case |
|------|------------|----------|
| `nelson_siegel` | β₀, β₁, β₂, τ | Government bond curves |
| `svensson` | β₀, β₁, β₂, β₃, τ₁, τ₂ | Extended yield curves |
| `cubic_spline` | Knot points | Flexible interpolation |
| `zero_curve` | Bootstrap | Discount curve from instruments |
| `forward_curve` | Derived | Forward rates from spot |

### Volatility Surfaces
| Type | Parameters | Use Case |
|------|------------|----------|
| `sabr` | α, β, ρ, ν | Options implied vol |
| `svi` | 5 params | Vol smile fitting |
| `local_vol` | Grid | Dupire local volatility |

### Credit
| Type | Parameters | Use Case |
|------|------------|----------|
| `hazard_curve` | Piecewise | Default probabilities |
| `credit_spread` | Curve | Credit risk premium |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `KAMPE_HOST` | `0.0.0.0` | Server bind address |
| `KAMPE_PORT` | `8002` | Server port |
| `KAMPE_DEBUG` | `false` | Debug mode |
| `KAMPE_ARITHMOS__URL` | `http://localhost:8001` | Arithmos service URL |
| `KAMPE_ARITHMOS__TIMEOUT` | `30.0` | Arithmos request timeout |

## Architecture Notes

- **Stateful**: Maintains model state (unlike stateless Arithmos)
- **Self-contained**: Model fitting logic lives in Kampe, not Arithmos
- **In-memory store**: Current implementation; production would use persistent storage
- **Constraint-aware**: Supports iterative refinement with constraints
- **Type-indexed**: Fast lookup by model type (curves, vol, credit)

### Kampe vs Arithmos

| Concern | Kampe | Arithmos |
|---------|-------|----------|
| Purpose | Financial models | Econometric stats |
| Examples | Yield curves, vol surfaces | Regression, transforms |
| State | Stateful (versioned models) | Stateless |
| Domain | Finance-specific | General-purpose |
