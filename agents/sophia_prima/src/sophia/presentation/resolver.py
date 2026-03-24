"""Resolve prompt-time and delivery-time presentation policy."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sophia.gateway.models import DeliveryArtifact, OutboundMessage
from sophia.gateway.run_store import GatewayRunStore
from sophia.presentation.models import PresentationDeliveryDecision
from sophia.presentation.registry import PresentationRegistry
from sophia.presentation.renderers import (
    extract_markdown_table,
    rasterize_svg_to_png,
    render_markdown_table_png,
    render_markdown_table_svg,
    strip_markdown_tables,
)
from sophia.security.filesystem import WritePolicy

logger = logging.getLogger("sophia.presentation")


class PresentationResolver:
    """Apply channel-aware delivery policy after the agent drafts a response."""

    def __init__(
        self,
        *,
        registry: PresentationRegistry,
        artifact_dir: Path,
        write_policy: WritePolicy | None = None,
    ) -> None:
        self.registry = registry
        self.artifact_dir = artifact_dir
        self.write_policy = write_policy

    def resolve_outbound(
        self,
        *,
        outbound: OutboundMessage,
        user_message: str,
        run_store: GatewayRunStore | None = None,
    ) -> OutboundMessage:
        """Rewrite outbound delivery when the channel cannot present the text well."""
        decision = self._resolve_delivery_decision(
            channel=outbound.channel,
            user_message=user_message,
            assistant_text=outbound.text,
        )
        if decision.mode == "text":
            return outbound

        artifact = self._build_artifact(
            channel=outbound.channel,
            user_message=user_message,
            assistant_text=outbound.text,
            run_id=outbound.run_id,
            session_id=outbound.session_id,
            agent_id=outbound.agent_id,
            guide_name=decision.guide_name,
            preferred_mode=decision.mode,
            run_store=run_store,
        )
        if artifact is None:
            return outbound
        return OutboundMessage(
            text=decision.text,
            session_id=outbound.session_id,
            agent_id=outbound.agent_id,
            channel=outbound.channel,
            account_id=outbound.account_id,
            peer_id=outbound.peer_id,
            run_id=outbound.run_id,
            artifacts=(artifact,),
            delivery_mode=artifact.kind,
        )

    def _resolve_delivery_decision(
        self,
        *,
        channel: str,
        user_message: str,
        assistant_text: str,
    ) -> PresentationDeliveryDecision:
        capabilities = self.registry.get_channel_capabilities(channel)
        table_block = extract_markdown_table(assistant_text)
        if table_block is None or capabilities.supports_markdown_tables:
            return PresentationDeliveryDecision(mode="text", text=assistant_text)
        guide = self.registry.match_guide(channel=channel, text=user_message)
        mode = capabilities.preferred_structured_delivery.get("table", "document")
        fallback_mode = "document" if capabilities.supports_document_attachments else "text"
        if mode == "image" and not capabilities.supports_image_attachments:
            mode = fallback_mode
        cleaned = strip_markdown_tables(assistant_text)
        cleaned = _normalize_lead_text(cleaned, channel=channel)
        return PresentationDeliveryDecision(
            mode=mode,
            text=cleaned,
            guide_name=guide.name if guide is not None else None,
            reason="structured_table_on_table_unfriendly_channel",
            fallback_mode=fallback_mode,
        )

    def _build_artifact(
        self,
        *,
        channel: str,
        user_message: str,
        assistant_text: str,
        run_id: str | None,
        session_id: str,
        agent_id: str,
        guide_name: str | None,
        preferred_mode: str,
        run_store: GatewayRunStore | None,
    ) -> DeliveryArtifact | None:
        table_block = extract_markdown_table(assistant_text)
        if table_block is None:
            return None
        stem = f"{run_id or 'presentation'}_table"
        title = _infer_artifact_title(user_message)
        theme = self.registry.load_render_theme()
        svg_path = self.artifact_dir / f"{stem}.svg"
        output_path = svg_path
        if self.write_policy is not None:
            self.write_policy.ensure_allowed(svg_path, purpose="presentation_artifact")
        render_markdown_table_svg(
            table_markdown=table_block,
            output_path=svg_path,
            title=title,
            theme=theme,
        )
        kind = "document"
        mime_type = "image/svg+xml"
        if preferred_mode == "image":
            png_path = self.artifact_dir / f"{stem}.png"
            if self.write_policy is not None:
                self.write_policy.ensure_allowed(png_path, purpose="presentation_artifact")
            if rasterize_svg_to_png(svg_path=svg_path, output_path=png_path) or render_markdown_table_png(
                table_markdown=table_block,
                output_path=png_path,
                title=title,
                theme=theme,
            ):
                output_path = png_path
                kind = "image"
                mime_type = "image/png"
        artifact_id = f"presentation:{output_path.stem}"
        if run_store is not None:
            artifact_id = run_store.save_skill_artifact(
                skill_name=guide_name or "presentation-delivery",
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
                payload={
                    "kind": kind,
                    "mime_type": mime_type,
                    "path": str(output_path),
                    "source_svg_path": str(svg_path),
                    "channel": channel,
                    "reason": "structured_table_attachment",
                },
            )
        return DeliveryArtifact(
            artifact_id=artifact_id,
            kind=kind,
            mime_type=mime_type,
            path=str(output_path),
        )


def _normalize_lead_text(text: str, *, channel: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if collapsed:
        return collapsed
    if channel == "telegram":
        return "I attached the table because Telegram does not render text tables cleanly."
    return "I attached the structured output."


def _infer_artifact_title(user_message: str) -> str:
    cleaned = re.sub(r"\s+", " ", user_message).strip()
    if not cleaned:
        return "Structured Output"
    return cleaned[:80]
