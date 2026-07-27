"""Presentation config and SOP registry."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sophia.presentation.models import (
    ChannelCapabilities,
    PresentationGuide,
    PresentationPromptContext,
    PresentationRenderTheme,
)
from sophia.security.filesystem import ReadPolicy
from sophia.skills.loader import discover_skill_files, load_skill

logger = logging.getLogger("sophia.presentation")


class PresentationRegistry:
    """Loads compact presentation config plus lazy SOP guides."""

    def __init__(
        self,
        *,
        core_path: Path,
        channels_path: Path,
        rendering_path: Path,
        skills_root: Path,
        max_loaded_chars: int,
        read_policy: ReadPolicy | None = None,
    ) -> None:
        self.core_path = core_path
        self.channels_path = channels_path
        self.rendering_path = rendering_path
        self.skills_root = skills_root
        self.max_loaded_chars = max_loaded_chars
        self.read_policy = read_policy
        self._core_guidance: str | None = None
        self._guides: list[PresentationGuide] | None = None
        self._render_theme: PresentationRenderTheme | None = None

    def load_core_guidance(self) -> str:
        """Load compact always-on presentation axioms."""
        if self._core_guidance is not None:
            return self._core_guidance
        if not self.core_path.exists():
            self._core_guidance = ""
            return self._core_guidance
        if self.read_policy is not None:
            self.read_policy.ensure_allowed(self.core_path, purpose="presentation_core_path")
        self._core_guidance = self.core_path.read_text(encoding="utf-8").strip()
        return self._core_guidance

    def get_channel_capabilities(self, channel: str | None) -> ChannelCapabilities:
        """Load one channel capability descriptor."""
        normalized = (channel or "").strip().lower()
        if not normalized:
            return ChannelCapabilities(channel="")
        config_path = self.channels_path / f"{normalized}.json"
        if not config_path.exists():
            return ChannelCapabilities(channel=normalized)
        if self.read_policy is not None:
            self.read_policy.ensure_allowed(config_path, purpose="presentation_channel_config")
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        preferred = payload.get("preferred_structured_delivery")
        if not isinstance(preferred, dict):
            preferred = {}
        return ChannelCapabilities(
            channel=str(payload.get("channel") or normalized),
            supports_markdown_tables=bool(payload.get("supports_markdown_tables", True)),
            supports_image_attachments=bool(payload.get("supports_image_attachments", False)),
            supports_document_attachments=bool(payload.get("supports_document_attachments", False)),
            max_text_chars=int(payload.get("max_text_chars", 4000)),
            preferred_structured_delivery={
                str(key): str(value)
                for key, value in preferred.items()
                if str(key).strip() and str(value).strip()
            },
        )

    def load_render_theme(self) -> PresentationRenderTheme:
        """Load the render theme used for structured image/document artifacts."""
        if self._render_theme is not None:
            return self._render_theme
        theme_path = self.rendering_path / "png_table_theme.json"
        default_theme = PresentationRenderTheme()
        if not theme_path.exists():
            self._render_theme = default_theme
            return self._render_theme
        if self.read_policy is not None:
            self.read_policy.ensure_allowed(theme_path, purpose="presentation_render_theme")
        payload = json.loads(theme_path.read_text(encoding="utf-8"))
        self._render_theme = PresentationRenderTheme(
            font_family=str(payload.get("font_family") or default_theme.font_family),
            title_font_size=int(payload.get("title_font_size", default_theme.title_font_size)),
            body_font_size=int(payload.get("body_font_size", default_theme.body_font_size)),
            line_height=int(payload.get("line_height", default_theme.line_height)),
            margin=int(payload.get("margin", default_theme.margin)),
            char_width=float(payload.get("char_width", default_theme.char_width)),
            corner_radius=int(payload.get("corner_radius", default_theme.corner_radius)),
            background_start=str(payload.get("background_start") or default_theme.background_start),
            background_end=str(payload.get("background_end") or default_theme.background_end),
            panel_fill=str(payload.get("panel_fill") or default_theme.panel_fill),
            panel_stroke=str(payload.get("panel_stroke") or default_theme.panel_stroke),
            accent=str(payload.get("accent") or default_theme.accent),
            title_color=str(payload.get("title_color") or default_theme.title_color),
            header_color=str(payload.get("header_color") or default_theme.header_color),
            text_color=str(payload.get("text_color") or default_theme.text_color),
            divider_color=str(payload.get("divider_color") or default_theme.divider_color),
            shadow_color=str(payload.get("shadow_color") or default_theme.shadow_color),
            header_fill=str(payload.get("header_fill") or default_theme.header_fill),
        )
        return self._render_theme

    def list_guides(self) -> list[PresentationGuide]:
        """Load presentation guide metadata once."""
        if self._guides is not None:
            return self._guides
        guides: list[PresentationGuide] = []
        for skill_file in discover_skill_files(self.skills_root):
            try:
                relative = skill_file.resolve(strict=False).relative_to(
                    self.skills_root.resolve(strict=False)
                )
            except ValueError:
                continue
            if not relative.parts or relative.parts[0] != "presentation":
                continue
            try:
                manifest = load_skill(
                    skill_file,
                    max_body_chars=self.max_loaded_chars,
                    read_policy=self.read_policy,
                    metadata_only=True,
                )
            except Exception as exc:
                logger.warning("failed to load presentation guide %s: %s", skill_file, exc)
                continue
            guides.append(self._guide_from_manifest(manifest))
        self._guides = guides
        return guides

    def load_guide_body(self, name: str) -> str:
        """Load one guide body on demand."""
        for guide in self.list_guides():
            if guide.name != name:
                continue
            manifest = load_skill(
                guide.path,
                max_body_chars=self.max_loaded_chars,
                read_policy=self.read_policy,
                metadata_only=False,
            )
            return manifest.body
        return ""

    def resolve_prompt_context(
        self,
        *,
        channel: str | None,
        user_message: str,
    ) -> PresentationPromptContext:
        """Resolve compact prompt guidance for the current turn."""
        capabilities = self.get_channel_capabilities(channel)
        core_guidance = self.load_core_guidance()
        guide = self.match_guide(channel=channel, text=user_message)
        if guide is not None and not guide.body:
            body = self.load_guide_body(guide.name)
            guide = PresentationGuide(
                name=guide.name,
                description=guide.description,
                path=guide.path,
                channels=guide.channels,
                content_types=guide.content_types,
                trigger_terms=guide.trigger_terms,
                preferred_mode=guide.preferred_mode,
                fallback_mode=guide.fallback_mode,
                body=body,
            )
        return PresentationPromptContext(
            core_guidance=core_guidance,
            channel_summary=capabilities.prompt_summary(),
            guide=guide,
        )

    def match_guide(
        self,
        *,
        channel: str | None,
        text: str,
    ) -> PresentationGuide | None:
        """Pick the best presentation SOP by channel and message shape."""
        normalized_channel = (channel or "").strip().lower()
        inferred_types = _infer_content_types(text)
        message_terms = _tokens(text)
        best: tuple[float, PresentationGuide] | None = None
        for guide in self.list_guides():
            if guide.channels and normalized_channel not in guide.channels:
                continue
            score = 0.0
            if guide.content_types:
                score += float(len(set(guide.content_types) & inferred_types) * 5)
            if guide.trigger_terms:
                score += float(len(set(guide.trigger_terms) & message_terms) * 2)
            if guide.channels and normalized_channel in guide.channels:
                score += 1.0
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, guide)
        return None if best is None else best[1]

    @staticmethod
    def _guide_from_manifest(manifest) -> PresentationGuide:
        metadata = manifest.metadata
        return PresentationGuide(
            name=manifest.name,
            description=manifest.description,
            path=manifest.path,
            channels=_parse_csv_field(metadata.get("channels")),
            content_types=_parse_csv_field(metadata.get("content_types")),
            trigger_terms=_parse_csv_field(metadata.get("trigger_terms")),
            preferred_mode=str(metadata.get("preferred_mode") or "text").strip() or "text",
            fallback_mode=str(metadata.get("fallback_mode") or "text").strip() or "text",
            body=manifest.body,
        )


def _parse_csv_field(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return tuple(dict.fromkeys(values))


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in "".join(ch if ch.isalnum() else " " for ch in text).split()
        if len(token) >= 3
    }


def _infer_content_types(text: str) -> set[str]:
    lowered = text.lower()
    inferred: set[str] = set()
    if any(token in lowered for token in ("table", "calendar", "schedule", "compare", "ranking")):
        inferred.add("table")
    if "leaderboard" in lowered:
        inferred.add("leaderboard")
    if "matrix" in lowered:
        inferred.add("comparison")
    return inferred
