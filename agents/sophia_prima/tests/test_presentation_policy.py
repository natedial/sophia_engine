from __future__ import annotations

from pathlib import Path

import pytest

import sophia.presentation.resolver as presentation_resolver_module
from sophia.agent import AgentConfig, SophiaAgent
from sophia.config import Settings
from sophia.context import ConversationContext
from sophia.gateway.models import OutboundMessage
from sophia.presentation import PresentationRegistry, PresentationResolver


class DummyProvider:
    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages,
        tools=None,
        max_tokens: int = 4096,
    ):
        from sophia.llm.types import (
            CompletionResponse,
            Message,
            Role,
            StopReason,
            TokenUsage,
        )

        self.system_prompts.append(system)
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content="ok"),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )

    async def stream(self, **kwargs):  # pragma: no cover - stream disabled in test
        raise AssertionError("stream() should not be called in this test")

    async def close(self) -> None:
        return None


class DummyPylon:
    def get_tools(self, only_healthy: bool = True):
        return []

    async def execute_tool(self, name: str, payload: dict):
        raise AssertionError("No tool execution expected in this test")


def _write_presentation_files(root: Path) -> None:
    (root / "config" / "presentation" / "channels").mkdir(parents=True, exist_ok=True)
    (root / "config" / "presentation" / "rendering").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "presentation" / "telegram-tabular-delivery").mkdir(
        parents=True,
        exist_ok=True,
    )
    (root / "config" / "presentation" / "core.md").write_text(
        "# Presentation Core\n\n- Prefer attachments when tables will degrade.\n",
        encoding="utf-8",
    )
    (root / "config" / "presentation" / "channels" / "telegram.json").write_text(
        "{\n"
        '  "channel": "telegram",\n'
        '  "supports_markdown_tables": false,\n'
        '  "supports_image_attachments": true,\n'
        '  "supports_document_attachments": true,\n'
        '  "max_text_chars": 4000,\n'
        '  "preferred_structured_delivery": {"table": "image"}\n'
        "}\n",
        encoding="utf-8",
    )
    (root / "config" / "presentation" / "rendering" / "png_table_theme.json").write_text(
        "{\n"
        '  "font_family": "\\"JetBrains Mono\\", Menlo, Consolas, monospace",\n'
        '  "background_start": "#0B1020",\n'
        '  "background_end": "#172033",\n'
        '  "accent": "#38BDF8",\n'
        '  "title_color": "#F8FAFC",\n'
        '  "header_color": "#7DD3FC"\n'
        "}\n",
        encoding="utf-8",
    )
    (root / "skills" / "presentation" / "telegram-tabular-delivery" / "SKILL.md").write_text(
        "---\n"
        "name: telegram-tabular-delivery\n"
        "description: tabular telegram delivery\n"
        "channels: telegram\n"
        "content_types: table, calendar\n"
        "trigger_terms: table, calendar, schedule\n"
        "preferred_mode: image\n"
        "fallback_mode: document\n"
        "---\n\n"
        "Prefer an attachment instead of inline markdown tables.",
        encoding="utf-8",
    )


def test_presentation_registry_resolves_telegram_prompt_context(tmp_path: Path) -> None:
    _write_presentation_files(tmp_path)
    registry = PresentationRegistry(
        core_path=tmp_path / "config" / "presentation" / "core.md",
        channels_path=tmp_path / "config" / "presentation" / "channels",
        rendering_path=tmp_path / "config" / "presentation" / "rendering",
        skills_root=tmp_path / "skills",
        max_loaded_chars=2000,
    )

    prompt_context = registry.resolve_prompt_context(
        channel="telegram",
        user_message="Show this week's calendar in a table",
    )

    assert "Prefer attachments" in prompt_context.core_guidance
    assert prompt_context.channel_summary is not None
    assert "plain-text tables degrade" in prompt_context.channel_summary
    assert prompt_context.guide is not None
    assert prompt_context.guide.name == "telegram-tabular-delivery"
    assert "Prefer an attachment" in prompt_context.guide.body


def test_presentation_resolver_rewrites_telegram_table_to_png_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_presentation_files(tmp_path)
    registry = PresentationRegistry(
        core_path=tmp_path / "config" / "presentation" / "core.md",
        channels_path=tmp_path / "config" / "presentation" / "channels",
        rendering_path=tmp_path / "config" / "presentation" / "rendering",
        skills_root=tmp_path / "skills",
        max_loaded_chars=2000,
    )
    resolver = PresentationResolver(
        registry=registry,
        artifact_dir=tmp_path / ".sophia" / "presentation",
    )
    def _fake_rasterize(*, svg_path: Path, output_path: Path, max_pixel_size: int = 2400) -> bool:
        output_path.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
        return True

    monkeypatch.setattr(
        presentation_resolver_module,
        "rasterize_svg_to_png",
        _fake_rasterize,
    )

    outbound = resolver.resolve_outbound(
        outbound=OutboundMessage(
            text=(
                "Here is the calendar.\n\n"
                "| Release | Type |\n"
                "| --- | --- |\n"
                "| CPI | Key |\n"
            ),
            session_id="session-1",
            agent_id="sophia_prima",
            channel="telegram",
            account_id="default",
            peer_id="chat-1",
            run_id="run-1",
        ),
        user_message="Show this week's calendar in a table",
    )

    assert outbound.delivery_mode == "image"
    assert outbound.artifacts
    assert outbound.artifacts[0].kind == "image"
    assert outbound.artifacts[0].mime_type == "image/png"
    assert outbound.artifacts[0].path.endswith(".png")
    assert Path(outbound.artifacts[0].path).exists()
    assert "| Release |" not in outbound.text
    assert Path(outbound.artifacts[0].path).read_bytes().startswith(b"\x89PNG")


def test_presentation_resolver_falls_back_to_direct_png_render_when_rasterize_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("PIL")
    _write_presentation_files(tmp_path)
    registry = PresentationRegistry(
        core_path=tmp_path / "config" / "presentation" / "core.md",
        channels_path=tmp_path / "config" / "presentation" / "channels",
        rendering_path=tmp_path / "config" / "presentation" / "rendering",
        skills_root=tmp_path / "skills",
        max_loaded_chars=2000,
    )
    resolver = PresentationResolver(
        registry=registry,
        artifact_dir=tmp_path / ".sophia" / "presentation",
    )
    monkeypatch.setattr(
        presentation_resolver_module,
        "rasterize_svg_to_png",
        lambda **_kwargs: False,
    )

    outbound = resolver.resolve_outbound(
        outbound=OutboundMessage(
            text=(
                "Here is the calendar.\n\n"
                "| Release | Type |\n"
                "| --- | --- |\n"
                "| CPI | Key |\n"
            ),
            session_id="session-1",
            agent_id="sophia_prima",
            channel="telegram",
            account_id="default",
            peer_id="chat-1",
            run_id="run-direct-png",
        ),
        user_message="Show this week's calendar in a table",
    )

    assert outbound.delivery_mode == "image"
    assert outbound.artifacts
    assert outbound.artifacts[0].mime_type == "image/png"
    assert Path(outbound.artifacts[0].path).read_bytes().startswith(b"\x89PNG")


def test_presentation_resolver_falls_back_to_svg_document_when_png_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_presentation_files(tmp_path)
    registry = PresentationRegistry(
        core_path=tmp_path / "config" / "presentation" / "core.md",
        channels_path=tmp_path / "config" / "presentation" / "channels",
        rendering_path=tmp_path / "config" / "presentation" / "rendering",
        skills_root=tmp_path / "skills",
        max_loaded_chars=2000,
    )
    resolver = PresentationResolver(
        registry=registry,
        artifact_dir=tmp_path / ".sophia" / "presentation",
    )
    monkeypatch.setattr(
        presentation_resolver_module,
        "rasterize_svg_to_png",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        presentation_resolver_module,
        "render_markdown_table_png",
        lambda **_kwargs: False,
    )

    outbound = resolver.resolve_outbound(
        outbound=OutboundMessage(
            text=(
                "Here is the calendar.\n\n"
                "| Release | Type |\n"
                "| --- | --- |\n"
                "| CPI | Key |\n"
            ),
            session_id="session-1",
            agent_id="sophia_prima",
            channel="telegram",
            account_id="default",
            peer_id="chat-1",
            run_id="run-2",
        ),
        user_message="Show this week's calendar in a table",
    )

    assert outbound.delivery_mode == "document"
    assert outbound.artifacts[0].path.endswith(".svg")
    rendered = Path(outbound.artifacts[0].path).read_text(encoding="utf-8")
    assert "JetBrains Mono" in rendered
    assert "#38BDF8" in rendered
    assert "linearGradient" in rendered


def test_presentation_resolver_converts_inline_csv_to_attachment(tmp_path: Path) -> None:
    _write_presentation_files(tmp_path)
    registry = PresentationRegistry(
        core_path=tmp_path / "config" / "presentation" / "core.md",
        channels_path=tmp_path / "config" / "presentation" / "channels",
        rendering_path=tmp_path / "config" / "presentation" / "rendering",
        skills_root=tmp_path / "skills",
        max_loaded_chars=2000,
    )
    resolver = PresentationResolver(
        registry=registry,
        artifact_dir=tmp_path / ".sophia" / "presentation",
    )

    outbound = resolver.resolve_outbound(
        outbound=OutboundMessage(
            text=(
                "Attached: CSV file with tomorrow's key releases.\n\n"
                "Summary: 2 items attached.\n\n"
                "Filename: releases_2026-03-31_key_releases.csv\n\n"
                "Content:\n"
                "name,priority\n"
                "\"FOMC Press Release\",High\n"
                "\"H.15 Selected Interest Rates\",High\n\n"
                "If you want this exported as an actual CSV file attachment, I can push it now."
            ),
            session_id="session-1",
            agent_id="sophia_prima",
            channel="telegram",
            account_id="default",
            peer_id="chat-1",
            run_id="run-csv",
        ),
        user_message="Send tomorrow's key releases as an attachment right now.",
    )

    assert outbound.delivery_mode == "document"
    assert outbound.artifacts
    assert outbound.artifacts[0].kind == "document"
    assert outbound.artifacts[0].mime_type == "text/csv"
    assert outbound.artifacts[0].path.endswith(".csv")
    assert Path(outbound.artifacts[0].path).read_text(encoding="utf-8").startswith(
        "name,priority\n"
    )
    assert "Filename:" not in outbound.text
    assert "Content:" not in outbound.text


def test_presentation_resolver_converts_standalone_csv_block_to_attachment(
    tmp_path: Path,
) -> None:
    _write_presentation_files(tmp_path)
    registry = PresentationRegistry(
        core_path=tmp_path / "config" / "presentation" / "core.md",
        channels_path=tmp_path / "config" / "presentation" / "channels",
        rendering_path=tmp_path / "config" / "presentation" / "rendering",
        skills_root=tmp_path / "skills",
        max_loaded_chars=2000,
    )
    resolver = PresentationResolver(
        registry=registry,
        artifact_dir=tmp_path / ".sophia" / "presentation",
    )

    outbound = resolver.resolve_outbound(
        outbound=OutboundMessage(
            text=(
                "Attached: tomorrow_key_releases_2026-03-31.csv.\n\n"
                "tomorrow_key_releases_2026-03-31.csv\n"
                "fred_release_id,name\n"
                "101,FOMC Press Release\n"
                "18,H.15 Selected Interest Rates\n\n"
                "Source note: pulled from the platform release calendar."
            ),
            session_id="session-1",
            agent_id="sophia_prima",
            channel="telegram",
            account_id="default",
            peer_id="chat-1",
            run_id="run-csv-standalone",
        ),
        user_message="Send tomorrow's key releases as an attachment right now.",
    )

    assert outbound.delivery_mode == "document"
    assert outbound.artifacts
    assert outbound.artifacts[0].mime_type == "text/csv"
    assert Path(outbound.artifacts[0].path).read_text(encoding="utf-8").startswith(
        "fred_release_id,name\n"
    )
    assert "tomorrow_key_releases_2026-03-31.csv\nfred_release_id" not in outbound.text


def test_presentation_resolver_converts_csv_below_wrapper_to_attachment(
    tmp_path: Path,
) -> None:
    _write_presentation_files(tmp_path)
    registry = PresentationRegistry(
        core_path=tmp_path / "config" / "presentation" / "core.md",
        channels_path=tmp_path / "config" / "presentation" / "channels",
        rendering_path=tmp_path / "config" / "presentation" / "rendering",
        skills_root=tmp_path / "skills",
        max_loaded_chars=2000,
    )
    resolver = PresentationResolver(
        registry=registry,
        artifact_dir=tmp_path / ".sophia" / "presentation",
    )

    outbound = resolver.resolve_outbound(
        outbound=OutboundMessage(
            text=(
                "Attached: tomorrow_key_releases_2026-03-31.csv — desk-ready list.\n\n"
                "CSV below (copy/save as tomorrow_key_releases_2026-03-31.csv):\n\n"
                "Date,Priority,Release\n"
                "2026-03-31,High,FOMC Press Release\n"
                "2026-03-31,High,H.15 Selected Interest Rates\n\n"
                "Source note: pulled from the release calendar."
            ),
            session_id="session-1",
            agent_id="sophia_prima",
            channel="telegram",
            account_id="default",
            peer_id="chat-1",
            run_id="run-csv-wrapper",
        ),
        user_message="Send tomorrow's key releases as an attachment right now.",
    )

    assert outbound.delivery_mode == "document"
    assert outbound.artifacts
    assert outbound.artifacts[0].mime_type == "text/csv"
    assert Path(outbound.artifacts[0].path).read_text(encoding="utf-8").startswith(
        "Date,Priority,Release\n"
    )
    assert "CSV below" not in outbound.text


@pytest.mark.asyncio
async def test_agent_injects_presentation_guidance_for_telegram(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "personality.md").write_text(
        "# Sophia\n\n## Style\nPlain.\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "soul.md").write_text("Soul text", encoding="utf-8")
    _write_presentation_files(tmp_path)

    settings = Settings(
        personality_path=tmp_path / "config" / "personality.md",
        soul_path=tmp_path / "config" / "soul.md",
        lessons_path=tmp_path / "config" / "LESSONS.md",
        skills_path=tmp_path / "skills",
        presentation_core_path=tmp_path / "config" / "presentation" / "core.md",
        presentation_channels_path=tmp_path / "config" / "presentation" / "channels",
        presentation_rendering_path=tmp_path / "config" / "presentation" / "rendering",
        presentation_enabled=True,
        skills_enabled=False,
        openai_api_key="test-key",
        llm_model="test-model",
        memory_store_backend="memory",
        agent_fs_read_allowlist=f"{tmp_path / 'config'},{tmp_path / 'skills'},.sophia",
    )
    provider = DummyProvider()
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=DummyPylon(),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="session-1")
    context.metadata["channel"] = "telegram"

    _ = [
        event
        async for event in agent.run(
            "Show this week's calendar in a table",
            context,
        )
    ]

    assert provider.system_prompts
    prompt = provider.system_prompts[0]
    assert "Channel presentation constraints" in prompt
    assert "plain-text tables degrade" in prompt
    assert "Active presentation SOP" in prompt
