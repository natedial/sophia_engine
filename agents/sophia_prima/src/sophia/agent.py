"""Core Sophia agent - dual-loop architecture with event streaming."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, AsyncGenerator, Callable

from pylon import ErrorType, PreflightResult, Pylon, ToolResult

from sophia.config import Settings, get_settings
from sophia.context import ConversationContext, apply_transforms, summarize_long_tool_results
from sophia.events import (
    AgentEvent,
    agent_end,
    agent_start,
    message_delta,
    message_end,
    message_start,
    skill_activated,
    subagent_end,
    subagent_error,
    subagent_start,
    tool_execution_end,
    tool_execution_start,
    turn_end,
    turn_start,
)
from sophia.llm.base import ContentDelta, ModelProvider, StreamComplete
from sophia.llm.types import (
    CompletionResponse,
    Message,
    Role,
    ToolCall,
    ToolResultMessage,
    ToolSchema,
)
from sophia.memory import MemoryManager, MemoryManagerConfig, create_memory_store
from sophia.personality.loader import Personality, load_personality
from sophia.skills.models import SkillMatch
from sophia.skills.registry import SkillRegistry
from sophia.subagents import SubagentOrchestrator, SubagentProfile, SubagentResult, SubagentTask

# Type aliases for steering / follow-up callbacks
SteeringCallback = Callable[[], list[Message] | None]
FollowUpCallback = Callable[[], str | None]
logger = logging.getLogger("sophia.agent")


def _parse_lessons_markdown(raw: str) -> list[str]:
    """Parse markdown list/plain lines into lesson strings."""
    lessons: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        normalized = re.sub(r"^[-*]\s+", "", stripped)
        normalized = re.sub(r"^\d+\.\s+", "", normalized)
        normalized = normalized.strip()
        if not normalized:
            continue
        lessons.append(normalized)
    return lessons


class AgentConfig:
    """Tunables for the agent loop."""

    def __init__(
        self,
        *,
        max_tool_iterations: int = 10,
        stream: bool = True,
        context_transformers: list | None = None,
    ) -> None:
        self.max_tool_iterations = max_tool_iterations
        self.stream = stream
        self.context_transformers = context_transformers or [
            summarize_long_tool_results(),
        ]


class SophiaAgent:
    """
    Core Sophia agent with a dual-loop, event-streaming architecture.

    Outer loop: follow-up messages (multi-turn steering).
    Inner loop: tool calls + LLM round-trips.

    The provider is injected — this class never imports the Anthropic SDK.
    """

    def __init__(
        self,
        provider: ModelProvider,
        settings: Settings | None = None,
        pylon: Pylon | None = None,
        preflight_result: PreflightResult | None = None,
        agent_config: AgentConfig | None = None,
        memory_manager: MemoryManager | None = None,
        get_steering_messages: SteeringCallback | None = None,
        get_follow_up_messages: FollowUpCallback | None = None,
        canvas_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or get_settings()
        self.read_policy = self.settings.build_read_policy()
        self.write_policy = self.settings.build_write_policy()
        self.seed_lessons = self._load_lessons()
        self.pylon = pylon or Pylon()
        self.preflight_result = preflight_result
        self.config = agent_config or AgentConfig()
        self.canvas_id = canvas_id
        if memory_manager is not None:
            self.memory = memory_manager
            self.memory.set_seed_lessons(self.seed_lessons)
        else:
            if self.settings.memory_store_backend.lower().strip() == "sqlite":
                self.read_policy.ensure_allowed(
                    self.settings.memory_store_path,
                    purpose="memory_store_path",
                )
                self.write_policy.ensure_allowed(
                    self.settings.memory_store_path,
                    purpose="memory_store_path",
                )
            memory_store = create_memory_store(
                backend=self.settings.memory_store_backend,
                sqlite_path=self.settings.memory_store_path,
                semantic_search_enabled=self.settings.memory_semantic_search_enabled,
                lexical_weight=self.settings.memory_lexical_weight,
                semantic_weight=self.settings.memory_semantic_weight,
                embedding_provider=self.settings.memory_embedding_provider,
                embedding_enabled=self.settings.memory_embedding_enabled,
                embedding_model=self.settings.memory_embedding_model,
                embed_episodic=self.settings.memory_embed_episodic,
                embed_semantic=self.settings.memory_embed_semantic,
                query_use_embedding_index=self.settings.memory_query_use_embedding_index,
                embedding_openai_api_key=(
                    self.settings.memory_embedding_openai_api_key
                    or self.settings.openai_api_key
                ),
                embedding_openai_base_url=self.settings.memory_embedding_openai_base_url,
                embedding_timeout_sec=self.settings.memory_embedding_timeout_sec,
                embedding_retry_max_attempts=self.settings.memory_embedding_retry_max_attempts,
                embedding_retry_base_delay_sec=(
                    self.settings.memory_embedding_retry_base_ms / 1000.0
                ),
                embedding_retry_max_delay_sec=(
                    self.settings.memory_embedding_retry_max_ms / 1000.0
                ),
                embedding_retry_jitter=self.settings.memory_embedding_retry_jitter,
            )
            self.memory = MemoryManager(
                store=memory_store,
                config=MemoryManagerConfig(
                    enabled=self.settings.memory_enabled,
                    working_window=self.settings.memory_working_window,
                    lessons_recall_k=self.settings.memory_lessons_top_k,
                    episodic_recall_k=self.settings.memory_episodic_top_k,
                    semantic_recall_k=self.settings.memory_semantic_top_k,
                    lesson_promotion_min_repeats=(
                        self.settings.memory_lesson_promotion_min_repeats
                    ),
                    compaction_enabled=self.settings.memory_compaction_enabled,
                    compaction_every_n_turns=self.settings.memory_compaction_every_n_turns,
                    compaction_max_episodic_per_session=(
                        self.settings.memory_compaction_max_episodic_per_session
                    ),
                    compaction_batch_size=self.settings.memory_compaction_batch_size,
                ),
                seed_lessons=self.seed_lessons,
            )
        self.get_steering_messages = get_steering_messages
        self.get_follow_up_messages = get_follow_up_messages
        self.personality = self._load_personality()
        self.soul = self._load_soul()
        self.skills = SkillRegistry(
            skills_root=self.settings.skills_path,
            enabled=self.settings.skills_enabled,
            max_loaded_chars=self.settings.skills_max_loaded_chars,
            implicit_min_overlap=self.settings.skills_implicit_match_min_overlap,
            read_policy=self.read_policy,
        )
        self.subagent_profiles = self._build_subagent_profiles()
        self.subagents = SubagentOrchestrator(
            profiles=self.subagent_profiles,
            max_parallel_workers=self.settings.subagents_max_parallel_workers,
        )

    def _build_subagent_profiles(self) -> dict[str, SubagentProfile]:
        default_timeout = self.settings.subagents_default_timeout_sec
        default_iters = self.settings.subagents_default_max_tool_iterations
        default_budget = self.settings.subagents_default_token_budget_chars
        default_result_chars = self.settings.subagents_default_max_result_chars

        return {
            "research_worker": SubagentProfile(
                name="research_worker",
                instructions=(
                    "You are a delegated research worker. Use tools to gather evidence, "
                    "then return concise factual findings with key values and dates. "
                    "Include citations with source_path, page_number, and chunk_id for "
                    "material claims, and flag contradictory evidence."
                ),
                allowed_tools=None,
                max_tool_iterations=default_iters,
                timeout_sec=default_timeout,
                token_budget_chars=default_budget,
                max_result_chars=default_result_chars,
            ),
            "chart_worker": SubagentProfile(
                name="chart_worker",
                instructions=(
                    "You are a delegated chart worker. Use canvas creation tools to create "
                    "a chart relevant to the request, then report what was created."
                ),
                allowed_tools={
                    "create_timeseries_chart",
                    "create_comparison_chart",
                    "create_scatter_chart",
                    "create_yield_curve_chart",
                },
                max_tool_iterations=default_iters,
                timeout_sec=default_timeout,
                token_budget_chars=default_budget,
                max_result_chars=default_result_chars,
            ),
        }

    # ------------------------------------------------------------------
    # Personality
    # ------------------------------------------------------------------

    def _load_personality(self) -> Personality:
        self.read_policy.ensure_allowed(
            self.settings.personality_path,
            purpose="personality_path",
        )
        return load_personality(self.settings.personality_path)

    def _load_soul(self) -> str:
        soul_path = self.settings.soul_path
        self.read_policy.ensure_allowed(
            soul_path,
            purpose="soul_path",
        )
        if not soul_path.exists():
            logger.warning("Soul file not found: %s", soul_path)
            return ""
        return soul_path.read_text(encoding="utf-8").strip()

    def _load_lessons(self) -> list[str]:
        lessons_path = self.settings.lessons_path
        if not lessons_path.exists():
            return []

        self.read_policy.ensure_allowed(
            lessons_path,
            purpose="lessons_path",
        )
        raw = lessons_path.read_text(encoding="utf-8")
        return _parse_lessons_markdown(raw)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        context: ConversationContext | None = None,
        memory_context: str | None = None,
        active_skill: SkillMatch | None = None,
        active_tools: list[ToolSchema] | None = None,
        subagent_context: str | None = None,
    ) -> str:
        dynamic_context: dict[str, str] = {}

        if active_tools:
            tool_names = [t.name for t in active_tools]
            dynamic_context["Available tools"] = ", ".join(tool_names)
            dynamic_context["Tool use policy"] = (
                "When a user asks for data or computations and tools are available, "
                "you must call the appropriate tool(s) before answering. "
                "Do not fabricate numbers. If tools are unavailable, explain the limitation."
            )
            if "search_research" in tool_names:
                dynamic_context["Research retrieval policy"] = (
                    "When using Tholos research tools:\n"
                    "1) For broad/open questions, run 2-3 focused search_research calls "
                    "covering different angles (e.g., pro/neutral/critical).\n"
                    "2) Prefer precision defaults unless recall is too low: "
                    "keyword_weight=0.65, semantic_weight=0.35, min_lexical_score=0.08, "
                    "semantic_tail_mode='demote'.\n"
                    "3) Synthesize only from retrieved evidence and cite key claims in the "
                    "exact form (source_path: <path>, p.<page_number>, chunk_id: <id>). "
                    "Do not use shorthand like 'supabase:214' or unlabeled IDs.\n"
                    "4) Separate evidence from interpretation and explicitly note major "
                    "disagreement across sources.\n"
                    "5) If the user asks to inspect or dig into a citation, call "
                    "get_research_chunk with the cited chunk_id before answering.\n"
                    "6) If the user asks to narrow scope, pass search_research scope params "
                    "(run_id/run_ids, source_paths, exclude_source_paths, "
                    "source_path_prefix/source_path_contains, page bounds, date_from/date_to, "
                    "max_per_source).\n"
                    "7) End research answers with a short natural-language follow-up hint, "
                    "for example: 'If you want, ask why a specific claim appears in chunk_id "
                    "<id> and I'll unpack the exact passage.'"
                )
            if "fed_speaker_brief" in tool_names:
                dynamic_context["Fed Tracker policy"] = (
                    "When using Fed Textual Change Tracker tools:\n"
                    "1) For high-level questions about a Fed speaker's current stance or "
                    "rhetoric, start with fed_speaker_brief.\n"
                    "2) For analytical questions (e.g. 'how has X shifted?'), use "
                    "fed_speaker_question — it queries structured artifacts and returns "
                    "evidence-based answers.\n"
                    "3) For specific structural analysis, use the specialized tools:\n"
                    "   - fed_speaker_comparisons: t-1 diffs between consecutive speeches\n"
                    "   - fed_speaker_theme_drift: long-term evolution on a theme\n"
                    "   - fed_speaker_orphaned_concepts: themes that were emphasized then dropped\n"
                    "   - fed_speaker_timeline: chronological communication history\n"
                    "4) If a document may not yet be ingested, call fed_ingest_url first, "
                    "then query.\n"
                    "5) Use full speaker names as they appear in Federal Reserve publications "
                    "(e.g. 'Christopher J. Waller', 'Jerome H. Powell').\n"
                    "6) These tools analyze textual/sentiment patterns only — do not use them "
                    "for market pricing inference."
                )

        if self.preflight_result:
            service_status = self.preflight_result.for_system_prompt()
            if service_status:
                dynamic_context["Service status"] = service_status

        if self.canvas_id:
            dynamic_context["Active canvas"] = (
                f"Canvas ID: {self.canvas_id}\n"
                "Always use this canvas_id when calling visualization tools. "
                "Do not ask the user for a canvas ID."
            )

        if memory_context:
            dynamic_context["Memory context"] = memory_context

        if subagent_context:
            dynamic_context["Subagent findings"] = subagent_context

        if active_skill is not None:
            active_lines = [f"Name: {active_skill.skill.name}"]
            if active_skill.skill.description:
                active_lines.append(f"Description: {active_skill.skill.description}")
            active_lines.append(
                f"Match: {active_skill.reason} (score={active_skill.score:.2f})"
            )
            if active_skill.skill.allowed_tools is not None:
                if active_skill.skill.allowed_tools:
                    active_lines.append(
                        "Tool allowlist: " + ", ".join(active_skill.skill.allowed_tools)
                    )
                else:
                    active_lines.append("Tool allowlist: (none)")
            if active_skill.skill.read_allowlist:
                active_lines.append(
                    "Read scope: " + ", ".join(active_skill.skill.read_allowlist)
                )
            if active_skill.skill.write_allowlist:
                active_lines.append(
                    "Write scope: " + ", ".join(active_skill.skill.write_allowlist)
                )
            active_lines.append("Instructions:")
            active_lines.append(active_skill.skill.body)
            dynamic_context["Active skill"] = "\n".join(active_lines)

        system_prompt = self.personality.to_system_prompt(dynamic_context)
        if self.soul:
            system_prompt = f"{system_prompt}\n\n{self.soul}"
        return system_prompt

    @staticmethod
    def _build_enforced_tool_prompt(system_prompt: str) -> str:
        enforcement = (
            "\n\n## Tool Use Requirement\n"
            "If tools are available and the user asks for data or computations, "
            "you must call the appropriate tool(s) before answering. "
            "Do not answer from memory. If you skip tool calls, the response is invalid."
        )
        return f"{system_prompt}{enforcement}"

    @staticmethod
    def _build_hard_tool_prompt(system_prompt: str, tools: list[ToolSchema]) -> str:
        tool_names = ", ".join(tool.name for tool in tools) if tools else "(none)"
        enforcement = (
            "\n\n## Hard Tool Requirement\n"
            "Your previous response did not use tools. "
            "You must emit at least one valid tool call before any narrative answer.\n"
            f"Available tools: {tool_names}\n"
            "If no tool is suitable, explain why after first attempting the closest tool."
        )
        return f"{system_prompt}{enforcement}"

    @staticmethod
    def _build_citation_repair_prompt(
        system_prompt: str,
        *,
        allowed_chunk_ids: set[str],
    ) -> str:
        sorted_ids = sorted(allowed_chunk_ids)
        cited_ids = ", ".join(sorted_ids[:40]) if sorted_ids else "(none)"
        repair = (
            "\n\n## Citation Integrity Requirement\n"
            "If you cite chunk_id values, they must exactly match tool output from this turn. "
            "Do not fabricate citation IDs.\n"
            "Use exact citation format: (source_path: <path>, p.<page_number>, chunk_id: <id>). "
            "Do not use shorthand like 'supabase:214'.\n"
            f"Allowed chunk_id values: {cited_ids}\n"
            "Regenerate your answer now with valid citations only."
        )
        return f"{system_prompt}{repair}"

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    def _get_tool_schemas(self) -> list[ToolSchema]:
        """Get provider-agnostic tool schemas from pylon."""
        only_healthy = self.preflight_result is not None
        tool_defs = self.pylon.get_tools(only_healthy=only_healthy)
        return [
            ToolSchema(
                name=td.name,
                description=td.description,
                input_schema=td.to_generic_schema()["input_schema"],
            )
            for td in tool_defs
        ]

    @staticmethod
    def _should_enforce_tools(user_message: str, tools: list[ToolSchema]) -> bool:
        if not tools:
            return False

        message = user_message.lower()
        keywords = (
            "latest", "current", "value", "series", "observations", "data",
            "yield", "rate", "cpi", "gdp", "inflation", "unemployment",
            "treasury", "auction", "fed", "speech", "release",
            "compute", "regression", "mean", "median", "std",
            "percent change", "yoy", "mom", "moving average",
            "normalize", "log", "difference",
            "research", "evidence", "source", "sources", "study", "studies",
            "paper", "papers", "consensus", "view", "views",
            "citation", "citations", "cite", "cited",
            "document", "documents", "provenance",
            "tone", "rhetoric", "drift", "hawkish", "dovish",
            "fomc", "fed chair", "fed president", "fed governor",
        )
        if any(kw in message for kw in keywords):
            return True

        if re.search(
            r"\b(where|what)\b.{0,25}\b(from|source|document|documents|citation|citations)\b",
            message,
        ):
            return True

        if re.search(r"\bsection\s+\d+[a-z]?\b|§\s*\d+", message):
            return True

        if re.search(
            r"\bchunk(?:[_\-\s]?id)?\b|\bchunk[_\-][a-z0-9._:\-]+\b",
            message,
        ):
            return True

        # Fed-official role references (governor, chair, president of ... Fed)
        if re.search(
            r"\b(governor|chair(?:man|woman)?|vice\s+chair|president)\b"
            r".{0,30}"
            r"\b(fed|federal\s+reserve|reserve\s+bank)\b",
            message,
        ):
            return True

        # Reverse: "the Fed's governor", "FOMC members"
        if re.search(
            r"\b(fed|fomc|federal\s+reserve)\b.{0,20}\b(member|official|speaker|governor|chair|president)s?\b",
            message,
        ):
            return True

        # Rhetorical/analytical shift language near a person or institution
        return bool(
            re.search(
                r"\b(shift|pivot|evolv|chang|soften|harden|walk\s*back|temper|signal)"
                r".{0,40}"
                r"\b(stance|tone|rhetoric|language|messaging|position|view|outlook)\b",
                message,
            )
        )

    @staticmethod
    def _latest_user_text(context: ConversationContext) -> str:
        for msg in reversed(context.messages):
            if msg.role == Role.USER and msg.content:
                return msg.content
        return ""

    async def _execute_tool(self, tool_call: ToolCall, allowed: set[str]) -> ToolResult:
        if tool_call.name not in allowed:
            return ToolResult.fail(f"Unknown tool: {tool_call.name}", ErrorType.INVALID_INPUT)
        return await self.pylon.execute_tool(tool_call.name, tool_call.input)

    @staticmethod
    def _scope_tools_for_skill(
        tools: list[ToolSchema],
        active_skill: SkillMatch | None,
    ) -> list[ToolSchema]:
        if active_skill is None or active_skill.skill.allowed_tools is None:
            return tools

        allowed = set(active_skill.skill.allowed_tools)
        return [tool for tool in tools if tool.name in allowed]

    @staticmethod
    def _scope_tools_for_profile(
        tools: list[ToolSchema],
        profile: SubagentProfile,
    ) -> list[ToolSchema]:
        if profile.allowed_tools is None:
            return tools
        return [tool for tool in tools if tool.name in profile.allowed_tools]

    @staticmethod
    def _build_research_prefetch_input(
        user_message: str,
        *,
        query_override: str | None = None,
        recall_mode: bool = False,
    ) -> dict[str, Any]:
        query = re.sub(r"\s+", " ", (query_override or user_message or "").strip())
        if recall_mode:
            return {
                "query": query,
                "limit": 8,
                "keyword_weight": 0.45,
                "semantic_weight": 0.55,
                "min_lexical_score": 0.0,
                "semantic_tail_mode": "keep",
                "max_per_source": 2,
            }
        return {
            "query": query,
            "limit": 8,
            "keyword_weight": 0.65,
            "semantic_weight": 0.35,
            "min_lexical_score": 0.08,
            "semantic_tail_mode": "demote",
            "max_per_source": 2,
        }

    @staticmethod
    def _search_result_count(content: str) -> int:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return 0
        if not isinstance(payload, dict):
            return 0
        count = payload.get("count")
        if isinstance(count, int):
            return max(0, count)
        results = payload.get("results")
        if isinstance(results, list):
            return len(results)
        return 0

    @staticmethod
    def _extract_evidence_rows_from_tool_output(
        tool_name: str,
        content: str,
    ) -> list[dict[str, Any]]:
        if tool_name not in {"search_research", "get_research_chunk"}:
            return []
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []

        rows: list[dict[str, Any]] = []
        if tool_name == "search_research":
            results = payload.get("results")
            if isinstance(results, list):
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    chunk_id = result.get("chunk_id")
                    source_path = result.get("source_path")
                    page_number = result.get("page_number")
                    text = result.get("text")
                    if isinstance(chunk_id, str) and isinstance(text, str):
                        rows.append(
                            {
                                "chunk_id": chunk_id.strip(),
                                "source_path": source_path if isinstance(source_path, str) else "",
                                "page_number": page_number if isinstance(page_number, int) else None,
                                "text": text.strip(),
                                "hybrid_score": (
                                    float(result.get("hybrid_score"))
                                    if isinstance(result.get("hybrid_score"), (int, float))
                                    else 0.0
                                ),
                                "lexical_score": (
                                    float(result.get("lexical_score"))
                                    if isinstance(result.get("lexical_score"), (int, float))
                                    else 0.0
                                ),
                            }
                        )
        else:
            chunk_id = payload.get("chunk_id")
            source_path = payload.get("source_path")
            page_number = payload.get("page_number")
            text = payload.get("text")
            if isinstance(chunk_id, str) and isinstance(text, str):
                rows.append(
                    {
                        "chunk_id": chunk_id.strip(),
                        "source_path": source_path if isinstance(source_path, str) else "",
                        "page_number": page_number if isinstance(page_number, int) else None,
                        "text": text.strip(),
                        "hybrid_score": 0.0,
                        "lexical_score": 0.0,
                    }
                )
        return rows

    @staticmethod
    def _should_emit_evidence_fallback(user_message: str) -> bool:
        return bool(
            re.search(
                r"\b(report|reports|fallout|fallouts|next steps?|expect|expects|outlook)\b",
                (user_message or "").lower(),
            )
        )

    @staticmethod
    def _trim_sentence(text: str, *, max_chars: int = 260) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned:
            return ""
        if len(cleaned) <= max_chars:
            return cleaned
        clipped = cleaned[:max_chars]
        cutoff = max(clipped.rfind("."), clipped.rfind(";"), clipped.rfind(","))
        if cutoff >= max_chars // 2:
            return clipped[: cutoff + 1].strip()
        return f"{clipped.rstrip()}..."

    @classmethod
    def _build_evidence_fallback_response(
        cls,
        *,
        user_message: str,
        evidence_rows: list[dict[str, Any]],
    ) -> str | None:
        if not evidence_rows or not cls._should_emit_evidence_fallback(user_message):
            return None

        ranked_rows = sorted(
            evidence_rows,
            key=lambda row: (
                float(row.get("hybrid_score") or 0.0),
                float(row.get("lexical_score") or 0.0),
            ),
            reverse=True,
        )
        selected_rows: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for row in ranked_rows:
            source_key = str(row.get("source_path") or "").strip().lower()
            if source_key and source_key in seen_sources:
                continue
            selected_rows.append(row)
            if source_key:
                seen_sources.add(source_key)
            if len(selected_rows) >= 4:
                break
        if len(selected_rows) < 4:
            for row in ranked_rows:
                if row in selected_rows:
                    continue
                selected_rows.append(row)
                if len(selected_rows) >= 4:
                    break

        lines = ["Retrieved research evidence currently indicates:"]
        for row in selected_rows:
            snippet = cls._trim_sentence(str(row.get("text") or ""))
            if not snippet:
                continue
            source_path = str(row.get("source_path") or "unknown")
            page_number = row.get("page_number")
            page = page_number if isinstance(page_number, int) and page_number > 0 else "?"
            chunk_id = str(row.get("chunk_id") or "unknown")
            lines.append(
                f"- {snippet} (source_path: {source_path}, p.{page}, chunk_id: {chunk_id})"
            )

        if len(lines) == 1:
            return None

        lines.append(
            "If you want, ask why a specific claim appears in a chunk_id and I will unpack the exact passage."
        )
        return "\n".join(lines)

    @staticmethod
    def _build_research_probe_queries(user_message: str) -> list[str]:
        raw = re.sub(r"\s+", " ", (user_message or "").strip())
        raw = re.sub(r"\badn\b", "and", raw, flags=re.IGNORECASE)
        if not raw:
            return []

        stop_words = {
            "a", "an", "and", "any", "are", "as", "at", "be", "by", "do", "for",
            "from", "give", "how", "i", "in", "is", "it", "last", "me", "of", "on",
            "or", "our", "that", "the", "this", "to", "was", "what", "when", "where",
            "which", "who", "why", "with", "you", "your", "week", "specific", "broad",
            "range", "view", "views", "document", "documents", "citation", "citations",
            "being", "been", "down", "just", "only", "recent", "recently", "now",
            "out", "since", "report", "reports", "focus", "seem", "ruled", "ruling",
            "friday",
        }
        keywords: list[str] = []
        for token in re.findall(r"[a-z0-9]+", raw.lower()):
            if len(token) < 3:
                continue
            if token in stop_words:
                continue
            normalized = token[:-1] if token.endswith("s") and len(token) > 4 else token
            if normalized not in keywords:
                keywords.append(normalized)

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

        fallback_phrase = " ".join(keywords[:8]).strip()
        probes: list[str] = [raw]
        if fallback_phrase and fallback_phrase != raw.lower():
            probes.append(fallback_phrase)

        if "ieepa" in keywords and "tariff" in keywords:
            legal_probe_terms = ["ieepa", "tariff"]
            if "supreme" in keywords:
                legal_probe_terms.extend(["supreme", "court"])
            lowered_raw = raw.lower()
            if "ruling" in lowered_raw or "ruled" in lowered_raw:
                legal_probe_terms.append("ruling")
            probes.append(" ".join(legal_probe_terms))

        probes.extend(keywords[:4])

        deduped: list[str] = []
        seen: set[str] = set()
        for query in probes:
            normalized_query = query.strip()
            if not normalized_query:
                continue
            key = normalized_query.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized_query)
        return deduped

    @staticmethod
    def _extract_chunk_ids_from_tool_output(tool_name: str, content: str) -> set[str]:
        if tool_name not in {"search_research", "get_research_chunk"}:
            return set()
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return set()

        chunk_ids: set[str] = set()
        if isinstance(payload, dict):
            chunk_id = payload.get("chunk_id")
            if isinstance(chunk_id, str) and chunk_id.strip():
                chunk_ids.add(chunk_id.strip())
            results = payload.get("results")
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict):
                        item_chunk_id = item.get("chunk_id")
                        if isinstance(item_chunk_id, str) and item_chunk_id.strip():
                            chunk_ids.add(item_chunk_id.strip())
        return chunk_ids

    @staticmethod
    def _extract_chunk_ids_from_text(text: str) -> set[str]:
        chunk_ids = set()
        pattern = re.compile(
            r"chunk_id(?:\s*[:=]\s*|\s+)[\"'“”]?([A-Za-z0-9._:\-]+)",
            flags=re.IGNORECASE,
        )
        for match in pattern.finditer(text or ""):
            chunk_id = match.group(1).strip()
            if chunk_id:
                chunk_ids.add(chunk_id)
        return chunk_ids

    @classmethod
    def _has_invalid_chunk_citations(
        cls,
        text: str,
        *,
        allowed_chunk_ids: set[str],
    ) -> bool:
        lowered = (text or "").lower()
        for match in re.finditer(r"\(([^)]*supabase:\d+[^)]*)\)", text or "", flags=re.IGNORECASE):
            citation_block = match.group(1).lower()
            if "source_path" not in citation_block:
                return True

        # Citation blocks that include pages must include both source_path and chunk_id labels.
        for match in re.finditer(r"\(([^)]*p\.\s*\d+[^)]*)\)", text or "", flags=re.IGNORECASE):
            citation_block = match.group(1).lower()
            if "source_path" not in citation_block or "chunk_id" not in citation_block:
                return True

        cited = cls._extract_chunk_ids_from_text(text)
        if "chunk_id" in lowered and not cited:
            return True
        if not cited:
            return False
        return not cited.issubset(allowed_chunk_ids)

    @staticmethod
    def _requires_explicit_citations(user_message: str) -> bool:
        message = (user_message or "").lower()
        return bool(
            re.search(
                r"\b(citation|citations|cite|cited|source|sources|document|documents|"
                r"where.*from|what.*from)\b",
                message,
            )
        )

    @classmethod
    def _requires_research_citations(
        cls,
        user_message: str,
        tools: list[ToolSchema],
    ) -> bool:
        if cls._requires_explicit_citations(user_message):
            return True

        tool_names = {tool.name for tool in tools}
        if not ({"search_research", "get_research_chunk", "list_research_sources"} & tool_names):
            return False

        message = (user_message or "").lower()

        # Fast path for synthesis-style prompts that should be evidence-grounded.
        if re.search(
            r"\b(range of views|broad range|consensus|debate|research-backed|evidence)\b",
            message,
        ):
            return True

        # Legal/policy recency questions should not be answered from model memory.
        if re.search(
            r"\b(supreme court|ruling|struck down|section\s+\d+|§\s*\d+|last week|recent)\b",
            message,
        ):
            return True

        return False

    @staticmethod
    def _has_structured_citations(text: str) -> bool:
        lowered = (text or "").lower()
        return (
            "source_path:" in lowered
            and "chunk_id" in lowered
            and re.search(r"\bp\.\s*\d+", lowered) is not None
        )

    def _should_delegate_subagents(
        self,
        message: str,
        available_tools: list[ToolSchema],
    ) -> bool:
        if not self.settings.subagents_enabled:
            return False
        planned = self.subagents.plan_for_message(
            message=message,
            available_tools=available_tools,
            canvas_id=self.canvas_id,
        )
        return bool(planned)

    @staticmethod
    def _format_subagent_summary(result: SubagentResult) -> str:
        if result.success:
            summary = result.content.strip()
            if summary:
                return f"[{result.profile_name}] {summary}"
            return f"[{result.profile_name}] completed"
        error = result.error or "Unknown subagent failure"
        return f"[{result.profile_name}] ERROR: {error}"

    def _build_subagent_context(self, results: list[SubagentResult]) -> str:
        lines = ["Delegated subagent outputs:"]
        for res in results:
            lines.append(f"- {self._format_subagent_summary(res)}")
        lines.append("Use these findings as additional context and validate where needed.")
        return "\n".join(lines)

    async def _run_subagent_task(
        self,
        task: SubagentTask,
        profile: SubagentProfile,
        parent_run_id: str,
    ) -> SubagentResult:
        sub_run_id = f"{parent_run_id}:{task.task_id}"
        context = ConversationContext(session_id=f"{task.task_id}:{sub_run_id}")
        context.add_user_message(task.prompt)

        available_tools = self._scope_tools_for_profile(self._get_tool_schemas(), profile)
        allowed_tool_names = {tool.name for tool in available_tools}
        worker_prompt = self._build_system_prompt(
            context=context,
            memory_context=None,
            active_skill=None,
            active_tools=available_tools,
        )
        worker_prompt = (
            f"{worker_prompt}\n\n"
            f"SUBAGENT PROFILE: {profile.name}\n"
            f"{profile.instructions}\n"
            "Return only execution findings for the supervisor. "
            "Do not address the user directly."
        )

        chars_used = 0
        iterations = 0
        last_message = ""

        while iterations < max(1, profile.max_tool_iterations):
            iterations += 1
            transformed = apply_transforms(context.messages, self.config.context_transformers)
            completion = await self.provider.complete(
                model=self.settings.llm_model,
                system=worker_prompt,
                messages=transformed,
                tools=available_tools or None,
            )

            assistant_msg = completion.message
            last_message = assistant_msg.content.strip()
            chars_used += len(assistant_msg.content)

            if chars_used > profile.token_budget_chars:
                return SubagentResult(
                    task_id=task.task_id,
                    profile_name=profile.name,
                    run_id=sub_run_id,
                    success=False,
                    error="Subagent token budget exceeded",
                    token_chars_used=chars_used,
                )

            context.add_assistant_message(assistant_msg)
            if not assistant_msg.tool_calls:
                content = last_message[: profile.max_result_chars]
                return SubagentResult(
                    task_id=task.task_id,
                    profile_name=profile.name,
                    run_id=sub_run_id,
                    success=True,
                    content=content,
                    token_chars_used=chars_used,
                )

            tool_results: list[ToolResultMessage] = []
            for tc in assistant_msg.tool_calls:
                result = await self._execute_tool(tc, allowed_tool_names)
                content = result.to_content()
                chars_used += len(content)
                if chars_used > profile.token_budget_chars:
                    return SubagentResult(
                        task_id=task.task_id,
                        profile_name=profile.name,
                        run_id=sub_run_id,
                        success=False,
                        error="Subagent token budget exceeded",
                        token_chars_used=chars_used,
                    )
                tool_results.append(
                    ToolResultMessage(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                    )
                )
            context.add_tool_results(tool_results)

        return SubagentResult(
            task_id=task.task_id,
            profile_name=profile.name,
            run_id=sub_run_id,
            success=False,
            error="Subagent max tool iterations reached",
            token_chars_used=chars_used,
        )

    # ------------------------------------------------------------------
    # Primary method — async generator of AgentEvents
    # ------------------------------------------------------------------

    async def run(
        self,
        message: str,
        context: ConversationContext,
        *,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        task_id: str | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        Process a user message, yielding AgentEvents as the agent works.

        This is the primary interface — callers iterate the generator and
        handle events (render text, show tool progress, etc.).
        """
        active_run_id = run_id or str(uuid.uuid4())
        yield agent_start(
            context.session_id,
            run_id=active_run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        )

        context.add_user_message(message)
        available_tools = self._get_tool_schemas()
        subagent_context: str | None = None
        if self._should_delegate_subagents(message, available_tools):
            tasks = self.subagents.plan_for_message(
                message=message,
                available_tools=available_tools,
                canvas_id=self.canvas_id,
            )
            child_run_ids: dict[str, str] = {}
            for delegated_task in tasks:
                profile_name = delegated_task.profile_name
                child_run_id = f"{active_run_id}:{delegated_task.task_id}"
                child_run_ids[delegated_task.task_id] = child_run_id
                yield subagent_start(
                    name=profile_name,
                    task=delegated_task.prompt,
                    run_id=child_run_id,
                    parent_run_id=active_run_id,
                    task_id=delegated_task.task_id,
                )

            results = await self.subagents.execute_plan(
                tasks=tasks,
                parent_run_id=active_run_id,
                run_worker=self._run_subagent_task,
            )
            for result in results:
                summary = self._format_subagent_summary(result)
                child_run_id = child_run_ids.get(
                    result.task_id,
                    f"{active_run_id}:{result.task_id}",
                )
                if result.success:
                    yield subagent_end(
                        name=result.profile_name,
                        summary=summary,
                        run_id=child_run_id,
                        parent_run_id=active_run_id,
                        task_id=result.task_id,
                    )
                else:
                    yield subagent_error(
                        name=result.profile_name,
                        error=result.error or "Unknown subagent failure",
                        timed_out=result.timed_out,
                        run_id=child_run_id,
                        parent_run_id=active_run_id,
                        task_id=result.task_id,
                    )
            if results:
                subagent_context = self._build_subagent_context(results)

        turn = 0

        # OUTER LOOP: follow-up messages
        while True:
            turn += 1
            yield turn_start(
                turn,
                run_id=active_run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
            )

            active_user_message = self._latest_user_text(context) or message
            active_skill = self.skills.match(active_user_message)
            if active_skill is not None:
                yield skill_activated(
                    name=active_skill.skill.name,
                    reason=active_skill.reason,
                    score=active_skill.score,
                    path=str(active_skill.skill.path),
                    run_id=active_run_id,
                    parent_run_id=parent_run_id,
                    task_id=task_id,
                )
            turn_tools = self._scope_tools_for_skill(available_tools, active_skill)
            allowed_tool_names = {tool.name for tool in turn_tools}
            memory_context = self.memory.recall_for_prompt(
                session_id=context.session_id,
                query=active_user_message,
                messages=context.messages,
            )
            system_prompt = self._build_system_prompt(
                context,
                memory_context,
                active_skill=active_skill,
                active_tools=turn_tools,
                subagent_context=subagent_context,
            )
            iterations = 0
            last_message: Message | None = None
            tools_required_for_turn = self._should_enforce_tools(
                active_user_message,
                turn_tools,
            )
            citations_required_for_turn = self._requires_research_citations(
                active_user_message,
                turn_tools,
            )
            tool_enforcement_attempts = 0
            used_tools_this_turn = False
            used_research_tools_this_turn = False
            cited_chunk_ids_seen: set[str] = set()
            evidence_by_chunk: dict[str, dict[str, Any]] = {}
            citation_repair_attempted = False

            # Deterministic bootstrap: prefetch evidence for citation-required
            # research prompts so the model starts with grounded context.
            if citations_required_for_turn and "search_research" in allowed_tool_names:
                probe_queries = self._build_research_probe_queries(active_user_message)[:3]
                successful_prefetches = 0
                for probe_index, probe_query in enumerate(probe_queries):
                    prefetch_call = ToolCall(
                        id=f"prefetch-search-research-{turn}-{probe_index}",
                        name="search_research",
                        input=self._build_research_prefetch_input(
                            active_user_message,
                            query_override=probe_query,
                            recall_mode=probe_index > 0,
                        ),
                    )
                    yield tool_execution_start(
                        prefetch_call,
                        run_id=active_run_id,
                        parent_run_id=parent_run_id,
                        task_id=task_id,
                    )
                    prefetch_result = await self._execute_tool(prefetch_call, allowed_tool_names)
                    prefetch_content = prefetch_result.to_content()
                    used_tools_this_turn = True
                    # Note: do NOT set used_research_tools_this_turn here.
                    # The prefetch is a speculative bootstrap — citation enforcement
                    # should only activate when the LLM itself chooses research tools.
                    cited_chunk_ids_seen.update(
                        self._extract_chunk_ids_from_tool_output(
                            prefetch_call.name,
                            prefetch_content,
                        )
                    )
                    for row in self._extract_evidence_rows_from_tool_output(
                        prefetch_call.name,
                        prefetch_content,
                    ):
                        chunk_id = str(row.get("chunk_id") or "").strip()
                        if chunk_id and chunk_id not in evidence_by_chunk:
                            evidence_by_chunk[chunk_id] = row
                    context.add_assistant_message(
                        Message(
                            role=Role.ASSISTANT,
                            tool_calls=[prefetch_call],
                        )
                    )
                    context.add_tool_results(
                        [
                            ToolResultMessage(
                                tool_call_id=prefetch_call.id,
                                content=prefetch_content,
                                is_error=not prefetch_result.success,
                            )
                        ]
                    )
                    yield tool_execution_end(
                        prefetch_call,
                        prefetch_content,
                        is_error=not prefetch_result.success,
                        run_id=active_run_id,
                        parent_run_id=parent_run_id,
                        task_id=task_id,
                    )
                    if prefetch_result.success and self._search_result_count(prefetch_content) > 0:
                        successful_prefetches += 1
                        if successful_prefetches >= 2:
                            break
                if cited_chunk_ids_seen:
                    system_prompt = self._build_citation_repair_prompt(
                        system_prompt,
                        allowed_chunk_ids=cited_chunk_ids_seen,
                    )

            # INNER LOOP: tool calls
            while iterations < self.config.max_tool_iterations:
                iterations += 1

                # Check for steering messages
                if self.get_steering_messages:
                    steering = self.get_steering_messages()
                    if steering:
                        context.messages.extend(steering)

                # Apply context transforms
                transformed = apply_transforms(
                    context.messages, self.config.context_transformers
                )

                # Call provider
                yield message_start(
                    run_id=active_run_id,
                    parent_run_id=parent_run_id,
                    task_id=task_id,
                )

                if self.config.stream:
                    completion = None
                    async for event in self._stream_and_yield(
                        system_prompt,
                        transformed,
                        turn_tools,
                        run_id=active_run_id,
                        parent_run_id=parent_run_id,
                        task_id=task_id,
                    ):
                        if isinstance(event, AgentEvent):
                            yield event
                        else:
                            # It's the CompletionResponse
                            completion = event
                    assert completion is not None
                else:
                    completion = await self.provider.complete(
                        model=self.settings.llm_model,
                        system=system_prompt,
                        messages=transformed,
                        tools=turn_tools or None,
                    )

                assistant_msg = completion.message
                yield message_end(
                    assistant_msg,
                    run_id=active_run_id,
                    parent_run_id=parent_run_id,
                    task_id=task_id,
                )

                # Add assistant message to context
                context.add_assistant_message(assistant_msg)
                last_message = assistant_msg

                # If no tool calls, check enforcement then break
                if not assistant_msg.tool_calls:
                    if (
                        tools_required_for_turn
                        and not used_tools_this_turn
                        and tool_enforcement_attempts < 2
                    ):
                        tool_enforcement_attempts += 1
                        if tool_enforcement_attempts == 1:
                            system_prompt = self._build_enforced_tool_prompt(system_prompt)
                        else:
                            system_prompt = self._build_hard_tool_prompt(system_prompt, turn_tools)
                        # Remove the assistant message we just added and retry
                        context.messages.pop()
                        continue

                    if tools_required_for_turn and not used_tools_this_turn:
                        assistant_msg.content = (
                            "I couldn't ground this response in live tool output, so I won't "
                            "synthesize from memory. Please retry and I'll run the research "
                            "tools first."
                        )
                        context.messages[-1] = assistant_msg

                    has_invalid_chunk_citations = self._has_invalid_chunk_citations(
                        assistant_msg.content,
                        allowed_chunk_ids=cited_chunk_ids_seen,
                    )
                    has_structured_citations = self._has_structured_citations(
                        assistant_msg.content
                    )
                    citation_issue = (
                        has_invalid_chunk_citations
                        or (
                            citations_required_for_turn
                            and used_research_tools_this_turn
                            and not has_structured_citations
                        )
                    )

                    # If cited chunk IDs don't match retrieved chunks, force one repair pass.
                    if (
                        not citation_repair_attempted
                        and citation_issue
                    ):
                        citation_repair_attempted = True
                        system_prompt = self._build_citation_repair_prompt(
                            system_prompt,
                            allowed_chunk_ids=cited_chunk_ids_seen,
                        )
                        context.messages.pop()
                        continue
                    if citation_repair_attempted and citation_issue:
                        fallback = self._build_evidence_fallback_response(
                            user_message=active_user_message,
                            evidence_rows=list(evidence_by_chunk.values()),
                        )
                        if fallback:
                            assistant_msg.content = fallback
                        else:
                            assistant_msg.content = (
                                "I couldn't produce citation-grounded output from the research "
                                "tool results in this turn. Please retry and I will fetch sources "
                                "again before summarizing."
                            )
                        context.messages[-1] = assistant_msg

                    break

                # Execute tool calls
                tool_results: list[ToolResultMessage] = []
                _RESEARCH_TOOL_NAMES = {"search_research", "get_research_chunk", "list_research_sources"}
                for tc in assistant_msg.tool_calls:
                    used_tools_this_turn = True
                    if tc.name in _RESEARCH_TOOL_NAMES:
                        used_research_tools_this_turn = True
                    yield tool_execution_start(
                        tc,
                        run_id=active_run_id,
                        parent_run_id=parent_run_id,
                        task_id=task_id,
                    )

                    result = await self._execute_tool(tc, allowed_tool_names)
                    content = result.to_content()
                    is_error = not result.success
                    cited_chunk_ids_seen.update(
                        self._extract_chunk_ids_from_tool_output(tc.name, content)
                    )
                    for row in self._extract_evidence_rows_from_tool_output(tc.name, content):
                        chunk_id = str(row.get("chunk_id") or "").strip()
                        if chunk_id and chunk_id not in evidence_by_chunk:
                            evidence_by_chunk[chunk_id] = row

                    yield tool_execution_end(
                        tc,
                        content,
                        is_error,
                        run_id=active_run_id,
                        parent_run_id=parent_run_id,
                        task_id=task_id,
                    )

                    tool_results.append(
                        ToolResultMessage(
                            tool_call_id=tc.id,
                            content=content,
                            is_error=is_error,
                        )
                    )

                    # Check steering between tool calls
                    if self.get_steering_messages:
                        steering = self.get_steering_messages()
                        if steering:
                            context.messages.extend(steering)
                            break  # Skip remaining tools, re-enter inner loop

                # Add tool results to context
                context.add_tool_results(tool_results)

            yield turn_end(
                turn,
                run_id=active_run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
            )

            if last_message is not None:
                self.memory.ingest_turn(
                    session_id=context.session_id,
                    user_message=active_user_message,
                    assistant_message=last_message.content,
                )

            # Check follow-up messages → continue outer loop or break
            if self.get_follow_up_messages:
                follow_up = self.get_follow_up_messages()
                if follow_up:
                    context.add_user_message(follow_up)
                    continue

            break

        yield agent_end(
            context.session_id,
            run_id=active_run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        )

    # ------------------------------------------------------------------
    # Streaming helper
    # ------------------------------------------------------------------

    async def _stream_and_yield(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema],
        *,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        task_id: str | None = None,
    ) -> AsyncGenerator[AgentEvent | CompletionResponse, None]:
        """Stream from provider, yielding AgentEvents for deltas and the
        CompletionResponse as the final item."""
        async for event in self.provider.stream(
            model=self.settings.llm_model,
            system=system,
            messages=messages,
            tools=tools or None,
        ):
            if isinstance(event, ContentDelta):
                yield message_delta(
                    event.text,
                    run_id=run_id,
                    parent_run_id=parent_run_id,
                    task_id=task_id,
                )
            elif isinstance(event, StreamComplete):
                yield event.response

    # ------------------------------------------------------------------
    # Convenience method
    # ------------------------------------------------------------------

    async def chat(self, message: str, context: ConversationContext) -> Message:
        """Consume run() and return the final assistant message.

        This is a simpler interface for callers that don't need event streaming.
        """
        last_message: Message | None = None
        async for event in self.run(message, context):
            if event.type.value == "message_end":
                last_message = event.data["message"]

        if last_message is None:
            return Message(role=Role.ASSISTANT, content="No response generated.")

        return last_message
