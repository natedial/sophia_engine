# Sophia Pylon

Gateway layer for backend service integration. Pylon routes queries from consumers to backend services for data and computation, and can expose those tools over MCP for agent orchestrators such as Hermes.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Consumers                           │
│  Hermes / MCP agents   │  scripts  │  other sophia_core     │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                      Sophia Pylon                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │    Tools    │  │   Routing   │  │      Clients        │ │
│  │ definitions │  │    logic    │  │   (HTTP clients)    │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend Services                         │
│ Scrivener │ Arithmos │ Tholos │ Oikonomia │ Brave Search │
│ data:8000 │ compute  │ research│ models     │ live web     │
└─────────────────────────────────────────────────────────────┘
```

## Installation

```bash
cd sophia_pylon
pip install -e .
```

## Usage

### For MCP Consumers (Hermes)

Install the MCP extra:

```bash
cd services/sophia_pylon
pip install -e ".[mcp]"
```

Run the Streamable HTTP MCP server:

```bash
sophia-pylon-mcp --host 0.0.0.0 --port 8091 --path /mcp
```

Hermes MCP configuration:

```yaml
mcp_servers:
  sophia:
    url: "http://localhost:8091/mcp"
    tools:
      include:
        - "*"
```

The MCP server exposes all `Pylon.get_tools()` definitions plus:

| Tool | Description |
|------|-------------|
| `sophia_pylon_preflight` | Reports backend service health and available/unavailable tools |

### For Python LLM Consumers

```python
from pylon import Pylon, PylonConfig

# Initialize
config = PylonConfig(
    scrivener_url="http://localhost:8000",
    arithmos_url="http://localhost:8001",
    brave_api_key="your-brave-api-key",
)
pylon = Pylon(config)

# Get tool definitions for LLM
tools = pylon.get_tools_as_anthropic_schema()

# Execute tools (called by LLM)
result = await pylon.execute_tool("get_latest_value", {"series_id": "FEDFUNDS"})
result = await pylon.execute_tool("compute", {
    "data": [{"date": "2024-01-01", "value": 100}, ...],
    "computations": [{"type": "mean"}, {"type": "linear_regression"}]
})

# Health check
health = await pylon.health_check()
# {"scrivener": True, "arithmos": True}
```

### For Direct Access (non-LLM)

```python
from pylon import Pylon

pylon = Pylon()

# Access Scrivener client directly
data = await pylon.scrivener.get_latest_value("GDP")
auctions = await pylon.scrivener.get_auctions(security_type="Note", days=30)

# Access Arithmos client directly
types = await pylon.arithmos.get_computation_types()
results = await pylon.arithmos.compute(
    data=[{"date": "2024-01-01", "value": 100}, ...],
    computations=[{"type": "mean"}, {"type": "std_dev"}],
    output="summary"
)

# Access Brave directly
web = await pylon.brave.search_web(query="latest CPI release", count=5)
```

## Adding a New Service

1. **Create the client** in `src/pylon/clients/`:

```python
# src/pylon/clients/world_model.py
from pylon.clients.base import BaseClient

class WorldModelClient(BaseClient):
    @property
    def name(self) -> str:
        return "world_model"

    async def health_check(self) -> bool:
        # ...

    async def get_state(self) -> dict:
        # ...
```

2. **Define tools** in `src/pylon/tools/`:

```python
# src/pylon/tools/world_model.py
from pylon.tools.base import ToolDefinition, ToolParameter, ToolParameterType

WORLD_MODEL_TOOLS = [
    ToolDefinition(
        name="get_market_state",
        description="Get current market state assessment",
        parameters=[],
    ),
]

class WorldModelToolExecutor:
    def __init__(self, client: WorldModelClient):
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        return WORLD_MODEL_TOOLS

    async def execute(self, tool_name: str, parameters: dict) -> ToolResult:
        # ...
```

3. **Register in Pylon** (`src/pylon/core.py`):

```python
# In __init__
self._world_model_client = WorldModelClient(base_url=self.config.world_model_url)
self._world_model_executor = WorldModelToolExecutor(self._world_model_client)

# In _register_tools
for tool in self._world_model_executor.get_tools():
    self._tool_executors[tool.name] = self._world_model_executor
```

No changes needed in sophia_prima - it automatically gets the new tools.

## Pre-flight Checks

Run health checks before starting a conversation to know what's available:

```python
from pylon import Pylon

pylon = Pylon()
preflight = await pylon.preflight()

# Check overall status
if preflight.all_healthy:
    print("All services available")
else:
    print(preflight.summary())
    # Pre-flight check:
    #   ✗ scrivener: unavailable - Connection refused
    #   Unavailable tools: list_series, search_series, ...

# Get only healthy tools for LLM
tools = pylon.get_tools_as_anthropic_schema(only_healthy=True)

# Generate system prompt context about degraded services
status_text = preflight.for_system_prompt()
# Returns None if all healthy, or:
# "SERVICE STATUS:
#  - scrivener is currently unavailable: Connection refused
#  - The following tools are disabled: list_series, ..."
```

## Error Handling

All tool results are classified by error type:

```python
from pylon import ErrorType, ToolResult

# Error types
ErrorType.SERVICE_UNAVAILABLE  # Service down (transient)
ErrorType.TIMEOUT              # Request timed out (transient)
ErrorType.RATE_LIMITED         # Too many requests (transient)
ErrorType.NOT_FOUND            # Resource doesn't exist
ErrorType.INVALID_INPUT        # Bad parameters
ErrorType.UNAUTHORIZED         # Auth/permission issue
ErrorType.UNKNOWN              # Unclassified

# Creating results
result = ToolResult.ok(data)
result = ToolResult.fail("Series not found", ErrorType.NOT_FOUND)

# Checking results
result.success          # bool
result.error_type       # ErrorType or None
result.is_retryable     # True for transient errors

# LLM-friendly error content includes recovery hints
print(result.to_content())
# Error: Resource not found: Series 'INVALID' not found
# Error type: not_found
# Recovery hint: The requested resource was not found. Check if the
# identifier (e.g., series_id) is correct. Use search_series to find
# valid identifiers.
```

## Available Tools

### Scrivener (Economic Data)

| Tool | Description |
|------|-------------|
| `list_series` | List all available data series |
| `search_series` | Search series by keyword |
| `get_series_info` | Get series metadata |
| `get_latest_value` | Get most recent value |
| `get_observations` | Get historical time series |
| `get_series_change` | Calculate period change |
| `get_auctions` | Get Treasury auction results |
| `get_auction_summary` | Get auction statistics |
| `get_releases_upcoming` | Get upcoming economic releases |
| `get_releases_today` | Get today's releases |
| `get_releases_week` | Get this week's releases |
| `get_releases_summary` | Get release summary stats |
| `get_speeches` | Get Fed speeches |
| `get_speech` | Get specific speech by ID |
| `get_speakers` | List Fed speakers |

### Arithmos (Computation)

| Tool | Description |
|------|-------------|
| `list_computation_types` | List available computation types with parameters |
| `compute` | Execute computations on time series data |

**Available Computations:**
- **Descriptive Stats**: mean, median, std_dev, percentile, min_max, descriptive_stats
- **Annualization**: annualize_mom, annualize_qoq, compound_daily_rate, deannualize
- **Period Comparisons**: yoy_change, yoy_percent, mom_change, mom_percent, period_lookup
- **Regression**: linear_regression, multi_regression, rolling_regression
- **Transformations**: percent_change, difference, log_transform, cumulative, normalize, moving_average

### Brave (Live Web)

| Tool | Description |
|------|-------------|
| `search_web` | Search the live web with Brave and return ranked URLs plus snippets |
| `get_web_context` | Retrieve Brave LLM Context with source-backed extracted content for grounding |

Brave is the current live-web layer in Pylon. It provides search and grounded content retrieval, not full browser automation.

## Configuration

```python
from pylon.core import PylonConfig

config = PylonConfig(
    scrivener_url="http://localhost:8000",
    arithmos_url="http://localhost:8001",
    brave_api_key="your-brave-api-key",
    # kampe_url="http://localhost:8002",  # Future
)
```

## Project Structure

```
sophia_pylon/
├── src/pylon/
│   ├── __init__.py
│   ├── core.py              # Main Pylon class
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── base.py          # BaseClient ABC
│   │   ├── brave.py         # Brave Search API client
│   │   ├── scrivener.py     # Scrivener HTTP client (data)
│   │   └── arithmos.py      # Arithmos HTTP client (computation)
│   └── tools/
│       ├── __init__.py
│       ├── base.py          # ToolDefinition, ToolResult, ErrorType
│       ├── brave.py         # Brave web retrieval tools
│       ├── scrivener.py     # Scrivener tool definitions
│       └── arithmos.py      # Arithmos tool definitions
├── pyproject.toml
└── README.md
```
