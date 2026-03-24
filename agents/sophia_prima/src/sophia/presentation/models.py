"""Typed models for presentation policy resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ChannelCapabilities:
    """Deterministic delivery capabilities for one channel."""

    channel: str
    supports_markdown_tables: bool = True
    supports_image_attachments: bool = False
    supports_document_attachments: bool = False
    max_text_chars: int = 4000
    preferred_structured_delivery: dict[str, str] = field(default_factory=dict)

    def prompt_summary(self) -> str | None:
        """Return a compact prompt-safe summary when the channel has real constraints."""
        constraints: list[str] = []
        if not self.supports_markdown_tables:
            constraints.append("plain-text tables degrade")
        if self.supports_image_attachments:
            constraints.append("image attachments supported")
        if self.supports_document_attachments:
            constraints.append("document attachments supported")
        if not constraints:
            return None
        return f"Channel={self.channel}; " + "; ".join(constraints)


@dataclass(frozen=True)
class PresentationGuide:
    """One lazily-loaded presentation SOP."""

    name: str
    description: str
    path: Path
    channels: tuple[str, ...] = ()
    content_types: tuple[str, ...] = ()
    trigger_terms: tuple[str, ...] = ()
    preferred_mode: str = "text"
    fallback_mode: str = "text"
    body: str = ""


@dataclass(frozen=True)
class PresentationPromptContext:
    """Prompt-facing presentation context for one turn."""

    core_guidance: str = ""
    channel_summary: str | None = None
    guide: PresentationGuide | None = None


@dataclass(frozen=True)
class PresentationRenderTheme:
    """Machine-readable render theme for presentation artifacts."""

    font_family: str = '"JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace'
    title_font_size: int = 24
    body_font_size: int = 18
    line_height: int = 28
    margin: int = 32
    char_width: float = 10.6
    corner_radius: int = 20
    background_start: str = "#0B1020"
    background_end: str = "#172033"
    panel_fill: str = "#0F172A"
    panel_stroke: str = "#334155"
    accent: str = "#38BDF8"
    title_color: str = "#F8FAFC"
    header_color: str = "#7DD3FC"
    text_color: str = "#E2E8F0"
    divider_color: str = "#475569"
    shadow_color: str = "#020617"
    header_fill: str = "#111B30"


@dataclass(frozen=True)
class PresentationDeliveryDecision:
    """Structured outbound delivery decision."""

    mode: str = "text"
    text: str = ""
    guide_name: str | None = None
    reason: str | None = None
    fallback_mode: str | None = None
