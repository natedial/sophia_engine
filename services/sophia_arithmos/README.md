# Sophia Arithmos

Computation and analysis engine for the Sophia ecosystem.

## Overview

Sophia Arithmos provides a REST API for performing statistical and econometric computations on time series data. It is designed to be called by sophia_pylon as part of the Sophia agent architecture.

```
sophia_prima (agent) → sophia_pylon (gateway) → sophia_arithmos (computation)
                                              → sophia_scrivener (data)
```

## Installation

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dependencies
pip install -e .

# Install dev dependencies
pip install -e ".[dev]"
```

## Running

```bash
# Copy and configure environment
cp .env.example .env

# Run the server
python -m sophia_arithmos.main

# Or with uvicorn directly
uvicorn sophia_arithmos.main:app --reload --port 8001
```

## API

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/compute/types` | GET | List available computation types |
| `/compute` | POST | Execute computations |

### Example Request

```bash
curl -X POST http://localhost:8001/compute \
  -H "Content-Type: application/json" \
  -d '{
    "data": [
      {"date": "2024-01-01", "value": 100},
      {"date": "2024-02-01", "value": 102.5},
      {"date": "2024-03-01", "value": 105}
    ],
    "computations": [
      {"type": "mean"},
      {"type": "percent_change"},
      {"type": "linear_regression"}
    ],
    "output": "latest"
  }'
```

### Example Response

```json
{
  "results": {
    "mean": {
      "latest": {"date": "2024-03-01", "value": 102.5},
      "summary": {"mean": 102.5, "n": 3}
    },
    "percent_change": {
      "latest": {"date": "2024-03-01", "value": 2.439}
    },
    "linear_regression": {
      "summary": {
        "slope": 2.5,
        "intercept": 100.0,
        "r_squared": 1.0
      }
    }
  },
  "metadata": {
    "input_points": 3,
    "computations_succeeded": 3
  }
}
```

## Available Computations

### Descriptive Statistics
- `mean` - Arithmetic mean
- `median` - Median value
- `std_dev` - Standard deviation
- `percentile` - Specific percentile (param: `q`)
- `min_max` - Minimum and maximum values
- `descriptive_stats` - Comprehensive statistics

### Compounding & Annualization
- `annualize_mom` - Month-over-month to annual
- `annualize_qoq` - Quarter-over-quarter to annual
- `annualize_days` - Annualize a rate that applies to N days
- `compound_daily_rate` - Compound daily rate over N days
- `compound_rates` - Compound multiple period rates together (see example below)
- `deannualize` - Annual to periodic rate
- `continuous_to_discrete` - Continuous to discrete compounding

### Period Comparisons
- `yoy_change` - Year-over-year absolute change
- `yoy_percent` - Year-over-year percentage change
- `mom_change` - Month-over-month absolute change
- `mom_percent` - Month-over-month percentage change
- `period_lookup` - Lookup value from N periods ago

### Regression
- `linear_regression` - Simple OLS regression on time
- `multi_regression` - Multiple regression (basic)
- `rolling_regression` - Rolling window regression

### Compounding Example: compound_rates

Compound multiple annualized rates over different periods:

```bash
curl -X POST http://localhost:8001/compute \
  -H "Content-Type: application/json" \
  -d '{
    "data": [
      {"date": "2024-01-01", "value": 3.5},
      {"date": "2024-01-11", "value": 3.6},
      {"date": "2024-01-21", "value": 0}
    ],
    "computations": [{"type": "compound_rates"}]
  }'
```

This compounds 3.5% annualized for 10 days with 3.6% annualized for the next 10 days, returning the combined annualized rate (3.55%).

### Transformations
- `percent_change` - Period-over-period percentage change
- `difference` - Period-over-period absolute difference
- `log_transform` - Natural log transformation
- `cumulative` - Cumulative sum or product
- `normalize` - Normalize to index/zscore/minmax
- `moving_average` - Simple moving average

## Configuration

Environment variables (prefix with `ARITHMOS_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8001` | Server port |
| `DEBUG` | `false` | Enable debug mode |
| `MAX_INPUT_POINTS` | `10000` | Max observations per request |
| `MAX_COMPUTATIONS` | `20` | Max computations per request |
| `DEFAULT_OUTPUT` | `latest` | Default output format |

### Precision Settings

Control decimal places for different data types:

| Setting | Default | Use Case |
|---------|---------|----------|
| `PRECISION__RATE` | `4` | Interest rates (3.4567%) |
| `PRECISION__PERCENT` | `2` | Percentages (2.75%) |
| `PRECISION__INDEX` | `2` | Index values (4532.21) |
| `PRECISION__RATIO` | `6` | Ratios (0.123456) |
| `PRECISION__CURRENCY` | `2` | Dollar amounts ($1234.56) |

## Adding New Computations

1. Create a new class inheriting from `Computation`:

```python
from sophia_arithmos.core.base import Computation
from sophia_arithmos.core.registry import registry
from sophia_arithmos.core.types import ComputationResult, Observation, OutputMode, ParamSpec

@registry.register
class MyComputation(Computation):
    name = "my_computation"
    description = "Description of what it does"
    params = {
        "window": ParamSpec(
            type="int",
            description="Window size",
            default=10,
        )
    }

    def compute(self, data: list[Observation], params: dict, output: OutputMode) -> ComputationResult:
        # Implementation here
        return ComputationResult(...)
```

2. Import the module in `computations/__init__.py`

## Testing

```bash
pytest
pytest --cov=sophia_arithmos
```

## Architecture Notes

- **Stateless**: Each request is self-contained
- **Precision**: Uses Decimal internally, rounds to configured precision on output
- **Batch**: Multiple computations can be requested in a single call
- **Extensible**: New computations are automatically registered via decorator
