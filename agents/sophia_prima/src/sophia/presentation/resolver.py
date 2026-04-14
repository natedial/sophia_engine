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
        csv_payload = extract_inline_csv_attachment(assistant_text)
        if csv_payload is not None and capabilities.supports_document_attachments:
            _, _, strip_start, strip_end = csv_payload
            cleaned = strip_inline_csv_attachment(
                assistant_text,
                start=strip_start,
                end=strip_end,
            )
            cleaned = _normalize_lead_text(cleaned, channel=channel)
            return PresentationDeliveryDecision(
                mode="document",
                text=cleaned,
                reason="inline_csv_attachment",
            )
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
        csv_payload = extract_inline_csv_attachment(assistant_text)
        if csv_payload is not None:
            return self._build_csv_artifact(
                csv_payload=csv_payload,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
                guide_name=guide_name,
                run_store=run_store,
            )

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

    def _build_csv_artifact(
        self,
        *,
        csv_payload: tuple[str | None, str, int, int],
        run_id: str | None,
        session_id: str,
        agent_id: str,
        guide_name: str | None,
        run_store: GatewayRunStore | None,
    ) -> DeliveryArtifact:
        filename, csv_content, _, _ = csv_payload
        safe_name = _sanitize_attachment_filename(
            filename,
            default=f"{run_id or 'presentation'}.csv",
        )
        output_path = self.artifact_dir / safe_name
        if self.write_policy is not None:
            self.write_policy.ensure_allowed(output_path, purpose="presentation_artifact")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(csv_content, encoding="utf-8")

        artifact_id = f"presentation:{output_path.stem}"
        if run_store is not None:
            artifact_id = run_store.save_skill_artifact(
                skill_name=guide_name or "presentation-delivery",
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
                payload={
                    "kind": "document",
                    "mime_type": "text/csv",
                    "path": str(output_path),
                    "channel": "telegram",
                    "reason": "inline_csv_attachment",
                },
            )

        return DeliveryArtifact(
            artifact_id=artifact_id,
            kind="document",
            mime_type="text/csv",
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


def extract_inline_csv_attachment(text: str) -> tuple[str | None, str, int, int] | None:
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1

    filename = _extract_csv_filename(normalized)
    start_index = _find_csv_start(lines)
    if start_index is None:
        return None

    csv_content, last_index = _collect_csv_lines(lines, start_index)
    if csv_content is None or last_index is None:
        return None

    strip_start_line = start_index
    probe = start_index - 1
    while probe >= 0:
        stripped = lines[probe].strip()
        if not stripped:
            strip_start_line = probe
            probe -= 1
            continue
        if _is_csv_metadata_line(stripped):
            strip_start_line = probe
            probe -= 1
            continue
        break

    strip_start = offsets[strip_start_line]
    strip_end = offsets[last_index] + len(lines[last_index])
    return filename, csv_content, strip_start, strip_end


def _collect_csv_lines(lines: list[str], start_index: int) -> tuple[str | None, int | None]:
    csv_lines: list[str] = []
    last_index: int | None = None
    for index in range(start_index, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            if csv_lines:
                break
            continue
        if not _looks_like_csv_row(line):
            if csv_lines:
                break
            continue
        csv_lines.append(line.rstrip())
        last_index = index

    if len(csv_lines) < 2:
        return None, None
    return "\n".join(csv_lines).rstrip() + "\n", last_index


def strip_inline_csv_attachment(text: str, *, start: int, end: int) -> str:
    return (text[:start] + text[end:]).strip()


def _sanitize_attachment_filename(filename: str | None, *, default: str) -> str:
    raw = (filename or "").strip()
    if not raw:
        return default
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)
    return sanitized or default


def _extract_csv_filename(text: str) -> str | None:
    match = re.search(r"([A-Za-z0-9._-]+\.csv)\b", text, flags=re.IGNORECASE)
    return match.group(1) if match is not None else None


def _find_csv_start(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if not _looks_like_csv_row(line):
            continue
        next_index = _next_nonempty_index(lines, index + 1)
        if next_index is None or not _looks_like_csv_row(lines[next_index]):
            continue
        return index
    return None


def _next_nonempty_index(lines: list[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return None


def _looks_like_csv_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "," not in stripped:
        return False
    if stripped.endswith(":") and stripped.lower().startswith("csv"):
        return False
    columns = [part.strip() for part in stripped.split(",")]
    non_empty = [part for part in columns if part]
    return len(non_empty) >= 2


def _is_csv_metadata_line(line: str) -> bool:
    lowered = line.lower()
    if lowered.startswith("filename:") or lowered.startswith("content:"):
        return True
    if lowered.startswith("csv below"):
        return True
    if re.fullmatch(r"[A-Za-z0-9._-]+\.csv", line, flags=re.IGNORECASE):
        return True
    return False
