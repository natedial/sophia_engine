# Sophia Agent Build Plan

## Overview

Sophia is a user-facing conversational agent that orchestrates backend services (data retrieval, world models, analysis) while maintaining a consistent personality defined via configuration. The agent supports multiple interaction channels: CLI, Web, and Telegram.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    sophia_prima (Agent Layer)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Personality │  │     LLM      │  │   Channel Adapters   │  │
│  │    System    │  │ Orchestrator │  │  (CLI, Web, Telegram)│  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    sophia_pylon (Gateway Layer)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │    Tools     │  │   Routing    │  │    HTTP Clients      │  │
│  │  Definitions │  │    Logic     │  │  (per service)       │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend Services                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  Scrivener  │  │ World Model │  │    Analysis Model       │ │
│  │ (Data API)  │  │   (TBD)     │  │       (TBD)             │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Key Design Principle:** sophia_prima doesn't know about individual backend services. It only talks to sophia_pylon, which handles all service routing and tool execution.

---

## Project Structure

```
sophia_core/
├── sophia_pylon/               # Gateway layer
│   ├── pyproject.toml
│   ├── README.md
│   └── src/pylon/
│       ├── __init__.py
│       ├── core.py             # Main Pylon class
│       ├── clients/
│       │   ├── base.py         # BaseClient ABC
│       │   └── scrivener.py    # Scrivener HTTP client
│       └── tools/
│           ├── base.py         # ToolDefinition, ToolResult
│           └── scrivener.py    # Scrivener tool definitions
│
├── sophia_prima/               # Agent layer
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── .env.example
│   │
│   ├── config/
│   │   └── personality.md      # Sophia's personality
│   │
│   └── src/sophia/
│       ├── __init__.py
│       ├── agent.py            # Core agent (uses Pylon)
│       ├── config.py           # Configuration
│       ├── cli.py              # CLI entry point
│       ├── personality/
│       │   └── loader.py       # MD → system prompt
│       └── channels/           # (future: web, telegram)
│
├── sophia_episto/              # Interview framework
├── sophia_onto/                # (future)
└── sophia_teleo/               # (future)
```

---

## Component Details

### 1. Personality System (sophia_prima)

**File: `config/personality.md`**

A markdown file defining Sophia's:
- Core identity and tone
- Domain expertise boundaries
- Response style guidelines
- Behavioral rules

**Loader** (`personality/loader.py`):
- Parses the MD file
- Constructs system prompt with dynamic context injection points
- Supports override sections per channel if needed

---

### 2. Core Agent (sophia_prima)

**File: `agent.py`**

The orchestrator that:
- Maintains conversation state
- Delegates tool execution to Pylon (doesn't know about individual services)
- Formats responses per personality guidelines
- Handles multi-step tool calling loops

**Key interfaces:**
```python
from pylon import Pylon

class SophiaAgent:
    def __init__(self, settings: Settings, pylon: Pylon):
        self.personality = load_personality(settings.personality_path)
        self.pylon = pylon  # Gateway - not individual services

    async def chat(self, message: str, context: ConversationContext) -> Response:
        """Main entry point for all channels"""
        tools = self.pylon.get_tools_as_anthropic_schema()
        # ... LLM call with tools ...
        result = await self.pylon.execute_tool(tool_name, params)
```

---

### 3. Gateway Layer (sophia_pylon)

Pylon is the single point of contact for all backend services. See `sophia_pylon/README.md` for full documentation.

**Key interfaces:**
```python
from pylon import Pylon, PylonConfig

config = PylonConfig(scrivener_url="http://localhost:8000")
pylon = Pylon(config)

# For LLM consumers
tools = pylon.get_tools_as_anthropic_schema()
result = await pylon.execute_tool("get_latest_value", {"series_id": "GDP"})

# For direct access
data = await pylon.scrivener.get_latest_value("GDP")
```

**Adding a new service:**
1. Create HTTP client in `pylon/clients/`
2. Define tools in `pylon/tools/`
3. Register in `pylon/core.py`
4. No changes needed in sophia_prima

---

### 4. Error Handling & Pre-flight (sophia_pylon)

**Error Types** (`pylon/tools/base.py`):
```python
class ErrorType(str, Enum):
    # Transient - may succeed on retry
    SERVICE_UNAVAILABLE = "service_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"

    # Permanent - won't succeed without changes
    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    UNAUTHORIZED = "unauthorized"

    UNKNOWN = "unknown"
```

**ToolResult with classification:**
```python
# Success
ToolResult.ok(data)

# Failure with type
ToolResult.fail("Series not found", ErrorType.NOT_FOUND)

# Check if retryable
result.is_retryable  # True for transient errors
```

**Error content for LLM includes recovery hints:**
```
Error: Resource not found: Series 'INVALID' not found
Error type: not_found
Recovery hint: The requested resource was not found. Check if the identifier
(e.g., series_id) is correct. Use search_series to find valid identifiers.
```

**Pre-flight checks:**
```python
preflight = await pylon.preflight()

# Returns PreflightResult:
#   all_healthy: bool
#   services: dict[str, ServiceStatus]  # name, healthy, latency_ms, error
#   available_tools: list[str]
#   unavailable_tools: list[str]

# For display
print(preflight.summary())

# For system prompt injection (returns None if all healthy)
status_text = preflight.for_system_prompt()
```

**Tool filtering:**
```python
# Get only tools from healthy services
tools = pylon.get_tools(only_healthy=True)
tools = pylon.get_tools_as_anthropic_schema(only_healthy=True)
```

---

### 5. Channel Adapters

#### Base Interface
```python
class BaseChannel(ABC):
    def __init__(self, agent: SophiaAgent): ...

    @abstractmethod
    async def start(self): ...

    @abstractmethod
    async def stop(self): ...
```

#### CLI Adapter (`channels/cli.py`)
- Interactive REPL using `prompt_toolkit` or similar
- Rich terminal output with `rich` library
- Session persistence (optional)

**Usage:**
```bash
sophia chat                    # Interactive mode
sophia ask "What is current GDP?"  # Single query
```

#### Web Adapter (`channels/web.py`)
- FastAPI application
- REST endpoint: `POST /chat`
- WebSocket endpoint: `/ws` for streaming responses
- Session management via headers/cookies

**Endpoints:**
```
POST /chat
  Body: { "message": "...", "session_id": "..." }
  Returns: { "response": "...", "session_id": "..." }

WS /ws
  Bidirectional streaming chat
```

#### Telegram Adapter (`channels/telegram.py`)
- Uses `python-telegram-bot` library
- Handles commands: `/start`, `/help`, `/clear`
- Maintains per-user conversation context
- Supports both private and group chats (configurable)

---

### 5. Configuration

**File: `.env`**
```bash
# LLM Provider
LLM_PROVIDER=anthropic          # anthropic | openai | local
ANTHROPIC_API_KEY=sk-...
LLM_MODEL=claude-sonnet-4-20250514

# Services
SCRIVENER_BASE_URL=http://localhost:8000

# Telegram (optional)
TELEGRAM_BOT_TOKEN=...

# Web (optional)
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

**File: `config.py`**
```python
@dataclass
class Config:
    personality_path: Path
    llm_provider: str
    llm_model: str
    scrivener_url: str
    telegram_token: Optional[str]
    web_host: str
    web_port: int
```

---

## Implementation Phases

### Phase 1: Foundation ✅
- [x] Project scaffolding (pyproject.toml, structure)
- [x] Configuration system (pydantic-settings)
- [x] Personality loader (MD → system prompt)
- [x] Core agent skeleton

### Phase 2: Scrivener Integration ✅
- [x] Scrivener HTTP client
- [x] Tool definitions for data queries
- [x] Agent tool execution loop (multi-step)
- [x] Response formatting with data

### Phase 3: CLI Channel ✅
- [x] Interactive REPL
- [x] Rich output formatting
- [x] Session/context management with tool history

### Phase 4: Architecture Refactor ✅
- [x] Extract gateway layer to sophia_pylon
- [x] Separate HTTP clients from tool definitions
- [x] Abstract service routing from agent
- [x] Document the new architecture

### Phase 5: Tool Use & Error Handling ✅
- [x] Error type classification (service_unavailable, not_found, invalid_input, etc.)
- [x] Recovery hints for LLM (guidance on how to handle each error type)
- [x] Pre-flight health checks with latency measurement
- [x] Service status injection into system prompt when degraded
- [x] Tool filtering based on service health

### Phase 6: Web Channel
- [ ] FastAPI application
- [ ] REST chat endpoint
- [ ] WebSocket support
- [ ] CORS configuration

### Phase 7: Telegram Channel
- [ ] Bot setup and webhook/polling
- [ ] Message handlers
- [ ] User session management
- [ ] Rate limiting

### Phase 8: Polish & Testing
- [ ] Unit tests for pylon clients
- [ ] Integration tests
- [ ] Logging and observability
- [ ] Retry logic for transient errors

---

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | Ecosystem compatibility with sophia_episto |
| LLM Client | `anthropic` SDK | Direct Anthropic API, tool use support |
| HTTP Client | `httpx` | Async support, modern API |
| Web Framework | FastAPI | Async, auto-docs, WebSocket support |
| Telegram | `python-telegram-bot` | Well-maintained, async support |
| CLI | `rich` + `prompt_toolkit` | Beautiful terminal UX |
| Config | `pydantic-settings` | Type-safe env loading |

---

## Future: Skills System

The architecture is designed to accommodate a skills system later without requiring refactoring. Skills would provide packaged multi-step workflows invokable via commands (e.g., `/briefing`, `/market-summary`).

**When to add skills:**
- Repeated patterns emerge requiring 3+ chained tool calls
- Users request saved routines or shortcuts
- Need to expose sophia_episto interviews as invokable capabilities

**Potential design:**
```python
# skills/base.py
class Skill(ABC):
    name: str           # e.g., "briefing"
    trigger: str        # e.g., "/briefing"
    description: str

    @abstractmethod
    async def execute(self, agent: SophiaAgent, context: ConversationContext) -> Response:
        """Run the skill's workflow"""
        pass

# skills/briefing.py
class MorningBriefingSkill(Skill):
    name = "briefing"
    trigger = "/briefing"
    description = "Generate morning market briefing"

    async def execute(self, agent, context):
        # 1. Fetch key rates
        # 2. Get recent auction results
        # 3. Summarize with personality
        ...
```

**Integration point in agent.py:**
```python
async def chat(self, message: str, context: ConversationContext) -> Response:
    # Future: skill invocation
    # if skill := self.skills.match(message):
    #     return await skill.execute(self, context)

    # Normal LLM flow
    ...
```

**Compatibility note:** sophia_episto uses a `.skill` archive format - future skills could potentially leverage or interoperate with this format.

---

## Open Questions

1. **LLM Selection**: Start with Claude? Support multiple providers?
2. **State Persistence**: In-memory only, or Redis/DB for sessions?
3. **Authentication**: Web API auth? Telegram user allowlists?
4. **Streaming**: Priority for streaming responses in web/CLI?
5. **Other Services**: What are the world model and analysis model APIs?

---

## Next Steps

1. Review and approve this plan
2. Create initial project scaffolding
3. Define `personality.md` content
4. Implement Phase 1 foundation
