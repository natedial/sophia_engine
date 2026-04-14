# Sophia Prima Temporal Research Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sophia Prima consistently honor temporal scope ("past 2 weeks", "this month"), anchor its reasoning to the current date, and produce informative scope-miss responses so that corpus-first research prompts behave deterministically.

**Architecture:** Five tight, independently-testable changes to `agents/sophia_prima/src/sophia/agent.py` plus companion tests in `agents/sophia_prima/tests/`. Changes are focused on pure helper methods (easy to TDD) plus one prompt-assembly change and one async integration point for corpus-inventory surfacing.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio, `datetime` stdlib, existing `re` usage in `agent.py`.

**Motivation (findings this plan addresses):**

1. The deterministic research prefetch (`_build_research_prefetch_input`, `agent.py:1253`) never translates natural-language time windows into `date_from`/`date_to`, so "past 2 weeks" is effectively ignored by the bootstrap call.
2. `_build_system_prompt` (`agent.py:402`) never injects today's date, so the model has to guess from its training cutoff when computing temporal arithmetic.
3. `_build_research_probe_queries` (`agent.py:1545-1553`) hard-codes an IEEPA/tariff-biased `priority_order` that distorts probes for other domains (e.g. "Iran conflict").
4. `_build_local_research_scope_miss_response` (`agent.py:1441`) emits a generic apology when the corpus misses; the user can't tell what the corpus actually contains.

---

## File Structure

**Modified files:**
- `agents/sophia_prima/src/sophia/agent.py` — add `_extract_time_window`, inject date into system prompt, wire time window into prefetch input, de-bias probe priority, thread corpus summary into scope-miss response, add async `_fetch_corpus_inventory_summary`.

**New test files:**
- `agents/sophia_prima/tests/test_agent_time_window.py` — unit tests for `_extract_time_window` (pure function).
- `agents/sophia_prima/tests/test_agent_research_prefetch.py` — tests for `_build_research_prefetch_input` behavior with/without temporal phrases.
- `agents/sophia_prima/tests/test_agent_probe_queries.py` — tests for `_build_research_probe_queries` ranking.
- `agents/sophia_prima/tests/test_agent_system_prompt_date.py` — test that system prompt includes current date.
- `agents/sophia_prima/tests/test_agent_scope_miss_corpus_summary.py` — tests for scope-miss response with corpus inventory.

**Rationale:** Each test file is scoped to one helper, matching the existing test file layout (`test_agent_local_tools.py`, `test_agent_skill_activation.py`, `test_agent_capability_adoption.py`). The helpers under test are either `@staticmethod`/`@classmethod` or instance methods that don't require full agent construction; tests use the existing pattern of `object.__new__(SophiaAgent)` or the `DummyProvider`/`DummyPylon` fixtures from `test_presentation_policy.py`.

---

## Task 1: Add `_extract_time_window` helper

Parses natural-language temporal phrases into `(date_from, date_to)` ISO date strings. Pure function, fully unit-testable with an injectable `now` for determinism.

**Files:**
- Modify: `agents/sophia_prima/src/sophia/agent.py:9` (add `timedelta` to datetime import)
- Modify: `agents/sophia_prima/src/sophia/agent.py:1252` (add new static method just above `_build_research_prefetch_input`)
- Create: `agents/sophia_prima/tests/test_agent_time_window.py`

- [ ] **Step 1: Write the failing tests**

Create `agents/sophia_prima/tests/test_agent_time_window.py`:

```python
from __future__ import annotations

from datetime import datetime, UTC

import pytest

from sophia.agent import SophiaAgent


FIXED_NOW = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)


def test_extract_past_two_weeks() -> None:
    result = SophiaAgent._extract_time_window(
        "What are the takes from the past 2 weeks?",
        now=FIXED_NOW,
    )
    assert result == ("2026-03-31", "2026-04-14")


def test_extract_last_30_days() -> None:
    result = SophiaAgent._extract_time_window(
        "Summarize research from the last 30 days.",
        now=FIXED_NOW,
    )
    assert result == ("2026-03-15", "2026-04-14")


def test_extract_previous_3_months() -> None:
    result = SophiaAgent._extract_time_window(
        "Show previous 3 months of desk notes.",
        now=FIXED_NOW,
    )
    assert result == ("2026-01-14", "2026-04-14")


def test_extract_bare_last_week() -> None:
    result = SophiaAgent._extract_time_window(
        "What happened last week?",
        now=FIXED_NOW,
    )
    assert result == ("2026-04-07", "2026-04-14")


def test_extract_bare_past_month() -> None:
    result = SophiaAgent._extract_time_window(
        "Give me takes from the past month.",
        now=FIXED_NOW,
    )
    assert result == ("2026-03-15", "2026-04-14")


def test_extract_this_week() -> None:
    # 2026-04-14 is a Tuesday → Monday is 2026-04-13.
    result = SophiaAgent._extract_time_window(
        "What has this week brought on GDP?",
        now=FIXED_NOW,
    )
    assert result == ("2026-04-13", "2026-04-14")


def test_extract_this_month() -> None:
    result = SophiaAgent._extract_time_window(
        "Takes from this month on Iran?",
        now=FIXED_NOW,
    )
    assert result == ("2026-04-01", "2026-04-14")


def test_extract_ytd() -> None:
    result = SophiaAgent._extract_time_window(
        "YTD research on labor markets.",
        now=FIXED_NOW,
    )
    assert result == ("2026-01-01", "2026-04-14")


def test_extract_year_to_date_phrase() -> None:
    result = SophiaAgent._extract_time_window(
        "Year to date research on labor markets.",
        now=FIXED_NOW,
    )
    assert result == ("2026-01-01", "2026-04-14")


def test_no_temporal_phrase_returns_none() -> None:
    assert (
        SophiaAgent._extract_time_window(
            "What do we think about GDP impact?",
            now=FIXED_NOW,
        )
        is None
    )


def test_empty_message_returns_none() -> None:
    assert SophiaAgent._extract_time_window("", now=FIXED_NOW) is None


def test_default_now_uses_current_utc() -> None:
    # When now is not passed, the function should still return a valid window
    # whose end date equals today (UTC). This keeps production calls simple.
    result = SophiaAgent._extract_time_window("past 7 days")
    assert result is not None
    date_from, date_to = result
    today = datetime.now(UTC).date().isoformat()
    assert date_to == today
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/sophia_prima && pytest tests/test_agent_time_window.py -v`
Expected: FAIL with `AttributeError: type object 'SophiaAgent' has no attribute '_extract_time_window'`

- [ ] **Step 3: Add `timedelta` to the datetime import**

In `agents/sophia_prima/src/sophia/agent.py`, change line 9:

```python
from datetime import UTC, datetime
```

to:

```python
from datetime import UTC, datetime, timedelta
```

- [ ] **Step 4: Implement `_extract_time_window`**

In `agents/sophia_prima/src/sophia/agent.py`, insert this method immediately before `_build_research_prefetch_input` (currently at line 1252 — insert just above the existing `@staticmethod` decorator for that method):

```python
    @staticmethod
    def _extract_time_window(
        user_message: str,
        *,
        now: datetime | None = None,
    ) -> tuple[str, str] | None:
        """Parse a natural-language temporal phrase into ISO date bounds.

        Returns ``(date_from, date_to)`` as ``'YYYY-MM-DD'`` strings when a
        recognized phrase is present, else ``None``. Used by the research
        prefetch to honor scope constraints like ``"past 2 weeks"`` without
        relying on the model to parse them independently.
        """
        if not user_message:
            return None
        reference = now or datetime.now(UTC)
        today = reference.date()
        lowered = user_message.lower()

        numeric_match = re.search(
            r"\b(?:past|last|previous)\s+(\d+)\s+(day|week|month)s?\b",
            lowered,
        )
        if numeric_match:
            quantity = int(numeric_match.group(1))
            unit = numeric_match.group(2)
            if unit == "day":
                delta = timedelta(days=quantity)
            elif unit == "week":
                delta = timedelta(weeks=quantity)
            else:
                delta = timedelta(days=quantity * 30)
            start = today - delta
            return (start.isoformat(), today.isoformat())

        bare_match = re.search(
            r"\b(?:past|last|previous)\s+(day|week|month)\b",
            lowered,
        )
        if bare_match:
            unit = bare_match.group(1)
            if unit == "day":
                delta = timedelta(days=1)
            elif unit == "week":
                delta = timedelta(weeks=1)
            else:
                delta = timedelta(days=30)
            start = today - delta
            return (start.isoformat(), today.isoformat())

        this_match = re.search(r"\bthis\s+(week|month)\b", lowered)
        if this_match:
            unit = this_match.group(1)
            if unit == "week":
                start = today - timedelta(days=today.weekday())
            else:
                start = today.replace(day=1)
            return (start.isoformat(), today.isoformat())

        if re.search(r"\b(?:ytd|year\s+to\s+date)\b", lowered):
            start = today.replace(month=1, day=1)
            return (start.isoformat(), today.isoformat())

        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd agents/sophia_prima && pytest tests/test_agent_time_window.py -v`
Expected: PASS (all 12 tests green)

- [ ] **Step 6: Commit**

```bash
git add agents/sophia_prima/src/sophia/agent.py agents/sophia_prima/tests/test_agent_time_window.py
git commit -m "Add _extract_time_window helper for temporal scope parsing"
```

---

## Task 2: Inject current date into the system prompt

Adds a `"Current date"` entry to the `dynamic_context` dictionary in `_build_system_prompt`, anchoring the model's temporal reasoning to runtime reality instead of training-cutoff guesses.

**Files:**
- Modify: `agents/sophia_prima/src/sophia/agent.py:415-417` (add one line after runtime inventory injection)
- Create: `agents/sophia_prima/tests/test_agent_system_prompt_date.py`

- [ ] **Step 1: Write the failing test**

Create `agents/sophia_prima/tests/test_agent_system_prompt_date.py`:

```python
from __future__ import annotations

import re
from datetime import UTC, datetime

from sophia.agent import SophiaAgent
from sophia.personality.loader import Personality


def _make_agent_stub() -> SophiaAgent:
    agent = object.__new__(SophiaAgent)
    agent.personality = Personality(raw_content="# Sophia\n\nTest persona.")
    agent.soul = None
    agent.runtime_component_inventory = None
    agent.preflight_result = None
    agent.canvas_id = None
    agent.profile = type(
        "StubProfile",
        (),
        {
            "agent_id": "sophia_prima",
            "label": "Sophia Prima",
            "description": None,
            "prompt": None,
            "tool_allowlist": None,
        },
    )()
    return agent


def test_system_prompt_contains_current_date() -> None:
    agent = _make_agent_stub()
    prompt = agent._build_system_prompt()
    expected_date = datetime.now(UTC).strftime("%Y-%m-%d")
    assert expected_date in prompt
    assert "Current date" in prompt


def test_system_prompt_date_format_includes_weekday() -> None:
    agent = _make_agent_stub()
    prompt = agent._build_system_prompt()
    # Format: "YYYY-MM-DD (Weekday)"
    assert re.search(
        r"\d{4}-\d{2}-\d{2} \((Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\)",
        prompt,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents/sophia_prima && pytest tests/test_agent_system_prompt_date.py -v`
Expected: FAIL — "Current date" is not in the prompt because the injection does not yet exist.

- [ ] **Step 3: Inject the current date in `_build_system_prompt`**

In `agents/sophia_prima/src/sophia/agent.py`, locate the block at lines 413-417:

```python
        dynamic_context: dict[str, str] = {}

        runtime_inventory_context = self._render_runtime_component_inventory()
        if runtime_inventory_context:
            dynamic_context["Runtime model inventory"] = runtime_inventory_context
```

Replace with:

```python
        dynamic_context: dict[str, str] = {}

        dynamic_context["Current date"] = datetime.now(UTC).strftime(
            "%Y-%m-%d (%A)"
        )

        runtime_inventory_context = self._render_runtime_component_inventory()
        if runtime_inventory_context:
            dynamic_context["Runtime model inventory"] = runtime_inventory_context
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents/sophia_prima && pytest tests/test_agent_system_prompt_date.py -v`
Expected: PASS (both tests green)

- [ ] **Step 5: Verify no existing tests regressed**

Run: `cd agents/sophia_prima && pytest tests/test_presentation_policy.py tests/test_agent_skill_activation.py -v`
Expected: PASS (pre-existing tests still pass — the new dynamic_context key is additive)

- [ ] **Step 6: Commit**

```bash
git add agents/sophia_prima/src/sophia/agent.py agents/sophia_prima/tests/test_agent_system_prompt_date.py
git commit -m "Inject current date into Sophia system prompt"
```

---

## Task 3: Wire `_extract_time_window` into `_build_research_prefetch_input`

The deterministic prefetch that grounds every corpus-first turn must apply the time window from the user message so "past 2 weeks" is honored on the first shot.

**Files:**
- Modify: `agents/sophia_prima/src/sophia/agent.py:1253-1278` (`_build_research_prefetch_input`)
- Create: `agents/sophia_prima/tests/test_agent_research_prefetch.py`

- [ ] **Step 1: Write the failing tests**

Create `agents/sophia_prima/tests/test_agent_research_prefetch.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from sophia.agent import SophiaAgent


FIXED_NOW = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)


def test_prefetch_passes_date_window_when_temporal_phrase_present() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "Based on research in our corpus from the past 2 weeks, takes on Iran?",
        now=FIXED_NOW,
    )
    assert result["date_from"] == "2026-03-31"
    assert result["date_to"] == "2026-04-14"
    assert result["limit"] == 8
    assert result["keyword_weight"] == 0.65
    assert result["semantic_weight"] == 0.35


def test_prefetch_omits_date_window_when_no_temporal_phrase() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "What do we think about GDP?",
        now=FIXED_NOW,
    )
    assert "date_from" not in result
    assert "date_to" not in result
    assert result["query"] == "What do we think about GDP?"


def test_prefetch_recall_mode_keeps_date_window() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "past 30 days of labor research",
        recall_mode=True,
        now=FIXED_NOW,
    )
    assert result["date_from"] == "2026-03-15"
    assert result["date_to"] == "2026-04-14"
    assert result["keyword_weight"] == 0.45
    assert result["semantic_weight"] == 0.55
    assert result["semantic_tail_mode"] == "keep"


def test_prefetch_query_override_uses_override_but_time_window_from_user_message() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "past 2 weeks, Iran conflict labor impact",
        query_override="iran labor",
        now=FIXED_NOW,
    )
    assert result["query"] == "iran labor"
    assert result["date_from"] == "2026-03-31"
    assert result["date_to"] == "2026-04-14"


def test_prefetch_this_week_window() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "what has this week brought on GDP",
        now=FIXED_NOW,
    )
    # 2026-04-14 is Tuesday; Monday is 2026-04-13
    assert result["date_from"] == "2026-04-13"
    assert result["date_to"] == "2026-04-14"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/sophia_prima && pytest tests/test_agent_research_prefetch.py -v`
Expected: FAIL — current `_build_research_prefetch_input` has no `now` kwarg and does not set `date_from`/`date_to`.

- [ ] **Step 3: Update `_build_research_prefetch_input`**

In `agents/sophia_prima/src/sophia/agent.py`, replace the existing method (lines 1252-1278) with:

```python
    @staticmethod
    def _build_research_prefetch_input(
        user_message: str,
        *,
        query_override: str | None = None,
        recall_mode: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        query = re.sub(r"\s+", " ", (query_override or user_message or "").strip())
        base_params: dict[str, Any] = {
            "query": query,
            "limit": 8,
            "max_per_source": 2,
        }
        time_window = SophiaAgent._extract_time_window(user_message, now=now)
        if time_window is not None:
            base_params["date_from"] = time_window[0]
            base_params["date_to"] = time_window[1]
        if recall_mode:
            base_params.update(
                {
                    "keyword_weight": 0.45,
                    "semantic_weight": 0.55,
                    "min_lexical_score": 0.0,
                    "semantic_tail_mode": "keep",
                }
            )
        else:
            base_params.update(
                {
                    "keyword_weight": 0.65,
                    "semantic_weight": 0.35,
                    "min_lexical_score": 0.08,
                    "semantic_tail_mode": "demote",
                }
            )
        return base_params
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/sophia_prima && pytest tests/test_agent_research_prefetch.py tests/test_agent_time_window.py -v`
Expected: PASS (Task 1 tests still green, new prefetch tests green)

- [ ] **Step 5: Commit**

```bash
git add agents/sophia_prima/src/sophia/agent.py agents/sophia_prima/tests/test_agent_research_prefetch.py
git commit -m "Honor temporal scope in research prefetch bootstrap"
```

---

## Task 4: De-bias `_build_research_probe_queries` priority ordering

Removes the hard-coded IEEPA/tariff priority bias from the generic keyword ranker. The domain-specific "IEEPA legal probe" at the bottom of the function (lines ~1567–1574) remains as a bonus probe — this change only affects how the *generic* keyword list is ordered.

**Files:**
- Modify: `agents/sophia_prima/src/sophia/agent.py:1545-1560` (replace `priority_order` dict and `sorted` call)
- Create: `agents/sophia_prima/tests/test_agent_probe_queries.py`

- [ ] **Step 1: Write the failing tests**

Create `agents/sophia_prima/tests/test_agent_probe_queries.py`:

```python
from __future__ import annotations

from sophia.agent import SophiaAgent


def test_probe_queries_rank_longer_keywords_first_for_geopolitical_query() -> None:
    probes = SophiaAgent._build_research_probe_queries(
        "what are the takes on GDP and labor impact of the Iran conflict?"
    )
    # The full raw message is always probe 0.
    assert probes[0].lower().startswith("what are the takes")

    # The compact keyword fallback should rank longer content words up front.
    # "conflict" (8), "impact" (6), "labor" (5), "iran" (4), "take" (4),
    # "gdp" (3). "week"/"past"/"our"/etc. are stop words.
    fallback = probes[1]
    assert "conflict" in fallback
    assert "iran" in fallback
    assert "impact" in fallback
    assert "labor" in fallback
    assert "gdp" in fallback
    conflict_idx = fallback.index("conflict")
    gdp_idx = fallback.index("gdp")
    assert conflict_idx < gdp_idx, (
        "Longer content terms should precede shorter ones in the fallback probe"
    )


def test_probe_queries_still_emit_legal_bonus_for_ieepa_tariff() -> None:
    probes = SophiaAgent._build_research_probe_queries(
        "What is the IEEPA tariff supreme court ruling status?"
    )
    # IEEPA legal bonus probe must still be present (rank-independent).
    joined = " | ".join(probes)
    assert "ieepa" in joined
    assert "tariff" in joined
    assert "supreme" in joined
    assert "court" in joined


def test_probe_queries_empty_input_returns_empty() -> None:
    assert SophiaAgent._build_research_probe_queries("") == []


def test_probe_queries_deduplicates() -> None:
    probes = SophiaAgent._build_research_probe_queries(
        "iran iran conflict conflict"
    )
    assert len(probes) == len(set(probes))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/sophia_prima && pytest tests/test_agent_probe_queries.py -v`
Expected: FAIL on `test_probe_queries_rank_longer_keywords_first_for_geopolitical_query` — the current priority_order dict biases ordering by IEEPA/tariff terms, not length, so the fallback will not be length-sorted.

- [ ] **Step 3: Replace `priority_order` with a length-based ranker**

In `agents/sophia_prima/src/sophia/agent.py`, locate the block at lines 1545-1560:

```python
        priority_order = {
            "ieepa": 0,
            "tariff": 1,
            "unconstitutional": 2,
            "supreme": 3,
            "court": 4,
            "section": 5,
        }
        keywords = sorted(
            keywords,
            key=lambda token: (
                priority_order.get(token, 100),
                -len(token),
                token,
            ),
        )
```

Replace with:

```python
        keywords = sorted(
            keywords,
            key=lambda token: (-len(token), token),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agents/sophia_prima && pytest tests/test_agent_probe_queries.py -v`
Expected: PASS (all 4 tests green)

- [ ] **Step 5: Sanity-check existing agent tests**

Run: `cd agents/sophia_prima && pytest tests/ -k "agent" -v`
Expected: PASS — no regression in the agent test suite.

- [ ] **Step 6: Commit**

```bash
git add agents/sophia_prima/src/sophia/agent.py agents/sophia_prima/tests/test_agent_probe_queries.py
git commit -m "Remove IEEPA bias from research probe keyword ranking"
```

---

## Task 5: Surface corpus inventory on scope-miss responses

When `_build_local_research_scope_miss_response` fires, proactively fetch `list_research_sources` via Pylon and summarize it into the response so the user sees what the corpus *does* contain. The static builder stays pure; a new async helper on the instance makes the tool call and passes the summary in.

**Files:**
- Modify: `agents/sophia_prima/src/sophia/agent.py:1440-1459` (`_build_local_research_scope_miss_response` accepts optional `corpus_summary`)
- Modify: `agents/sophia_prima/src/sophia/agent.py` (add `_fetch_corpus_inventory_summary` async instance method near other helpers, e.g. just above `_build_local_research_scope_miss_response`)
- Modify: `agents/sophia_prima/src/sophia/agent.py:2535-2540` (call site: fetch summary, pass it in)
- Modify: `agents/sophia_prima/src/sophia/agent.py:2695-2698` (second call site: fetch summary, pass it in)
- Create: `agents/sophia_prima/tests/test_agent_scope_miss_corpus_summary.py`

- [ ] **Step 1: Write the failing tests**

Create `agents/sophia_prima/tests/test_agent_scope_miss_corpus_summary.py`:

```python
from __future__ import annotations

import json
from typing import Any

import pytest

from sophia.agent import SophiaAgent


class _StubPylonResult:
    def __init__(self, *, success: bool, content: str) -> None:
        self.success = success
        self._content = content

    def to_content(self) -> str:
        return self._content


class _StubPylon:
    def __init__(self, payload: dict[str, Any] | None, *, success: bool = True) -> None:
        self._payload = payload
        self._success = success
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute_tool(self, name: str, payload: dict[str, Any]):
        self.calls.append((name, payload))
        content = json.dumps(self._payload) if self._payload is not None else "{}"
        return _StubPylonResult(success=self._success, content=content)


def test_scope_miss_response_includes_corpus_summary_when_provided() -> None:
    response = SophiaAgent._build_local_research_scope_miss_response(
        user_message="takes on Iran conflict past 2 weeks",
        fallback_reason="local_research_prefetch_returned_no_hits",
        corpus_summary="Corpus currently indexes 42 sources (e.g. fed_speeches, bls_reports).",
    )
    assert "42 sources" in response
    assert "fed_speeches" in response


def test_scope_miss_response_omits_summary_line_when_none() -> None:
    response = SophiaAgent._build_local_research_scope_miss_response(
        user_message="takes on Iran conflict past 2 weeks",
        fallback_reason="local_research_prefetch_returned_no_hits",
        corpus_summary=None,
    )
    assert "Corpus currently indexes" not in response
    assert "widen the corpus scope or switch to web" in response


def test_scope_miss_response_works_for_prefetch_failed_reason() -> None:
    response = SophiaAgent._build_local_research_scope_miss_response(
        user_message="takes on Iran conflict past 2 weeks",
        fallback_reason="local_research_prefetch_failed",
        corpus_summary="Corpus currently indexes 7 sources.",
    )
    assert "couldn't complete the corpus check" in response
    assert "7 sources" in response


@pytest.mark.asyncio
async def test_fetch_corpus_inventory_summary_returns_formatted_string() -> None:
    agent = object.__new__(SophiaAgent)
    agent.pylon = _StubPylon(
        {
            "sources": [
                {"source_path": "fed_speeches/powell_2026_04_10.pdf", "chunk_count": 12},
                {"source_path": "bls_reports/jobs_2026_04.pdf", "chunk_count": 7},
                {"source_path": "research/gdp_outlook_q2.pdf", "chunk_count": 5},
            ]
        }
    )
    summary = await agent._fetch_corpus_inventory_summary()
    assert summary is not None
    assert "3 sources" in summary
    assert "fed_speeches" in summary


@pytest.mark.asyncio
async def test_fetch_corpus_inventory_summary_returns_none_on_tool_failure() -> None:
    agent = object.__new__(SophiaAgent)
    agent.pylon = _StubPylon(None, success=False)
    summary = await agent._fetch_corpus_inventory_summary()
    assert summary is None


@pytest.mark.asyncio
async def test_fetch_corpus_inventory_summary_returns_none_when_empty() -> None:
    agent = object.__new__(SophiaAgent)
    agent.pylon = _StubPylon({"sources": []})
    summary = await agent._fetch_corpus_inventory_summary()
    assert summary is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agents/sophia_prima && pytest tests/test_agent_scope_miss_corpus_summary.py -v`
Expected: FAIL — `_build_local_research_scope_miss_response` does not yet accept `corpus_summary`, and `_fetch_corpus_inventory_summary` does not yet exist.

- [ ] **Step 3: Update `_build_local_research_scope_miss_response`**

In `agents/sophia_prima/src/sophia/agent.py`, replace the existing method (lines 1440-1459) with:

```python
    @staticmethod
    def _build_local_research_scope_miss_response(
        *,
        user_message: str,
        fallback_reason: str,
        corpus_summary: str | None = None,
    ) -> str:
        request = re.sub(r"\s+", " ", (user_message or "").strip())
        summary_line = ""
        if corpus_summary:
            summary_line = f"\nCorpus inventory: {corpus_summary}\n"
        if fallback_reason == "local_research_prefetch_failed":
            return (
                "I paused before using external sources because this looks like a local-first "
                "research request, but I couldn't complete the corpus check cleanly in this turn.\n\n"
                f"Request: {request}\n"
                f"{summary_line}"
                "\nIf you want, I can retry the corpus search, widen the corpus scope, or switch to web."
            )
        return (
            "I paused before using external sources because this looks like a local-first "
            "research request, but I couldn't find matching corpus hits in the current scope.\n\n"
            f"Request: {request}\n"
            f"{summary_line}"
            "\nIf you want, I can widen the corpus scope or switch to web."
        )
```

- [ ] **Step 4: Add the async `_fetch_corpus_inventory_summary` helper**

In `agents/sophia_prima/src/sophia/agent.py`, add this method immediately above `_build_local_research_scope_miss_response` (so both helpers live together):

```python
    async def _fetch_corpus_inventory_summary(self) -> str | None:
        """Fetch a one-line corpus inventory string for scope-miss responses.

        The shape of the ``list_research_sources`` payload is not strictly
        typed across Tholos versions. This helper accepts the three most
        likely shapes and returns ``None`` on any mismatch, so the caller can
        gracefully omit the inventory line.

        Accepted shapes:
        - ``{"sources": [{"source_path": "...", "chunk_count": N}, ...]}``
        - ``[{"source_path": "...", ...}, ...]`` (bare list)
        - ``{"results": [{"source_path": "...", ...}, ...]}``
        """
        if self.pylon is None:
            return None
        try:
            result = await self.pylon.execute_tool("list_research_sources", {})
        except Exception:
            return None
        if not getattr(result, "success", False):
            return None
        try:
            payload = json.loads(result.to_content())
        except json.JSONDecodeError:
            return None

        sources: list[Any] | None = None
        if isinstance(payload, list):
            sources = payload
        elif isinstance(payload, dict):
            for key in ("sources", "results", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    sources = value
                    break
        if not sources:
            return None

        total = len(sources)
        labels: list[str] = []
        for item in sources[:5]:
            if not isinstance(item, dict):
                continue
            raw_path = (
                item.get("source_path")
                or item.get("path")
                or item.get("name")
                or ""
            )
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            label = raw_path.strip().split("/", 1)[0]
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= 3:
                break

        if labels:
            example_str = ", ".join(labels)
            return f"Corpus currently indexes {total} sources (e.g. {example_str})."
        return f"Corpus currently indexes {total} sources."
```

- [ ] **Step 5: Update the two call sites to pass `corpus_summary`**

In `agents/sophia_prima/src/sophia/agent.py`, find the first call site at lines ~2535-2540:

```python
                        local_research_scope_miss_response = (
                            self._build_local_research_scope_miss_response(
                                user_message=active_user_message,
                                fallback_reason=fallback_reason,
                            )
                        )
```

Replace with:

```python
                        corpus_summary = await self._fetch_corpus_inventory_summary()
                        local_research_scope_miss_response = (
                            self._build_local_research_scope_miss_response(
                                user_message=active_user_message,
                                fallback_reason=fallback_reason,
                                corpus_summary=corpus_summary,
                            )
                        )
```

Then find the second call site at lines ~2695-2698:

```python
                                assistant_msg.content = self._build_local_research_scope_miss_response(
                                    user_message=active_user_message,
                                    fallback_reason="local_research_prefetch_returned_no_hits",
                                )
```

Replace with:

```python
                                corpus_summary = await self._fetch_corpus_inventory_summary()
                                assistant_msg.content = self._build_local_research_scope_miss_response(
                                    user_message=active_user_message,
                                    fallback_reason="local_research_prefetch_returned_no_hits",
                                    corpus_summary=corpus_summary,
                                )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd agents/sophia_prima && pytest tests/test_agent_scope_miss_corpus_summary.py -v`
Expected: PASS (all 6 tests green)

- [ ] **Step 7: Run the full agent test suite for regressions**

Run: `cd agents/sophia_prima && pytest tests/ -v`
Expected: PASS — all pre-existing tests continue to pass alongside the new ones.

- [ ] **Step 8: Commit**

```bash
git add agents/sophia_prima/src/sophia/agent.py agents/sophia_prima/tests/test_agent_scope_miss_corpus_summary.py
git commit -m "Surface corpus inventory on research scope-miss responses"
```

---

## Final verification

- [ ] **Step 1: Run the complete Sophia Prima test suite**

Run: `cd agents/sophia_prima && pytest tests/ -v`
Expected: PASS. Every new test file green, every pre-existing test still green.

- [ ] **Step 2: Run ruff lint on modified files**

Run: `cd agents/sophia_prima && ruff check src/sophia/agent.py tests/test_agent_time_window.py tests/test_agent_research_prefetch.py tests/test_agent_probe_queries.py tests/test_agent_system_prompt_date.py tests/test_agent_scope_miss_corpus_summary.py`
Expected: PASS — no lint errors.

- [ ] **Step 3: Manual smoke test (optional, requires live env)**

Source env, start the gateway, and issue the test prompt through a connected channel:

```bash
set -a && source /Users/ncdial/devwork/sophia_engine/infra/.env && set +a
```

Send: *"Based on available research in our corpus from the past 2 weeks, what are the takes on GDP and labor impact of the Iran conflict?"*

Expected trace:
1. System prompt contains `"Current date: 2026-04-14 (Tuesday)"`.
2. Prefetch `search_research` call includes `"date_from": "2026-03-31", "date_to": "2026-04-14"`.
3. If corpus misses: scope-miss response includes the inventory line.
4. If corpus hits: synthesis answer cites only chunks with dates on or after 2026-03-31.

---

## Out of scope (follow-ups)

- **Corpus coverage telemetry** — a scheduled report that enumerates Tholos chunk counts by topic over rolling windows. Needed to answer the deeper question "does our corpus actually have geopolitical research?" but is a new feature, not a fix to existing plumbing. File a separate plan.
- **LLM-driven temporal parsing** — for phrases the regex doesn't recognize ("since the Iran strike", "after the last FOMC"). Defer until we see real production misses justifying the additional cost.
- **Per-topic probe priority overrides** — if future evals reveal that specific macro themes need biased ranking, add targeted bonus probes (like the existing IEEPA legal probe) rather than reintroducing a global priority dict.
