"""Artifact renderers for structured presentation delivery."""

from __future__ import annotations

from html import escape
from pathlib import Path
import shutil
import subprocess
from typing import Any

try:  # pragma: no cover - exercised when Pillow is installed
    from PIL import Image, ImageColor, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - handled by runtime fallback
    Image = None
    ImageColor = None
    ImageDraw = None
    ImageFont = None

from sophia.presentation.models import PresentationRenderTheme


def render_markdown_table_svg(
    *,
    table_markdown: str,
    output_path: Path,
    title: str | None = None,
    theme: PresentationRenderTheme | None = None,
) -> None:
    """Render one markdown table block to a simple SVG document."""
    active_theme = theme or PresentationRenderTheme()
    lines = _format_markdown_table_as_monospace(table_markdown)
    title_line = title.strip() if title else ""
    all_lines = [title_line, ""] + lines if title_line else lines
    line_height = active_theme.line_height
    margin = active_theme.margin
    char_width = active_theme.char_width
    max_len = max((len(line) for line in all_lines), default=0)
    width = max(640, margin * 2 + max_len * char_width)
    height = max(240, margin * 2 + len(all_lines) * line_height)
    panel_x = 14
    panel_y = 14
    panel_width = width - 28
    panel_height = height - 28
    inner_width = panel_width - 36
    title_y = margin + active_theme.title_font_size + 2 if title_line else margin
    header_line_index = 3 if title_line else 1

    text_nodes: list[str] = []
    for index, line in enumerate(all_lines, start=1):
        y = margin + index * line_height
        is_title = bool(title_line and index == 1)
        is_header = index == header_line_index
        weight = "700" if is_title or is_header else "400"
        font_size = active_theme.title_font_size if is_title else active_theme.body_font_size
        fill = active_theme.text_color
        if is_title:
            y = title_y
            fill = active_theme.title_color
        elif is_header:
            fill = active_theme.header_color
        text_nodes.append(
            f'<text x="{margin}" y="{y}" font-family="{escape(active_theme.font_family)}" '
            f'font-size="{font_size}" font-weight="{weight}" fill="{fill}">{escape(line)}</text>'
        )

    header_y = margin + header_line_index * line_height
    header_rect_y = header_y - line_height + 8

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        "<defs>"
        '<linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">'
        f'<stop offset="0%" stop-color="{active_theme.background_start}"/>'
        f'<stop offset="100%" stop-color="{active_theme.background_end}"/>'
        "</linearGradient>"
        '<linearGradient id="accentGlow" x1="0%" y1="0%" x2="100%" y2="0%">'
        f'<stop offset="0%" stop-color="{active_theme.accent}" stop-opacity="0.20"/>'
        f'<stop offset="100%" stop-color="{active_theme.accent}" stop-opacity="0.03"/>'
        "</linearGradient>"
        "</defs>"
        f'<rect width="{width}" height="{height}" fill="url(#bg)" rx="{active_theme.corner_radius}" '
        f'ry="{active_theme.corner_radius}"/>'
        f'<rect x="{panel_x + 10}" y="{panel_y + 10}" width="{panel_width}" height="{panel_height}" '
        f'fill="{active_theme.shadow_color}" opacity="0.28" rx="{active_theme.corner_radius - 2}" '
        f'ry="{active_theme.corner_radius - 2}"/>'
        f'<rect x="{panel_x}" y="{panel_y}" width="{panel_width}" height="{panel_height}" '
        f'fill="{active_theme.panel_fill}" stroke="{active_theme.panel_stroke}" stroke-width="1.5" '
        f'rx="{active_theme.corner_radius - 2}" ry="{active_theme.corner_radius - 2}"/>'
        f'<rect x="{panel_x}" y="{panel_y}" width="{panel_width}" height="16" fill="url(#accentGlow)" '
        f'rx="{active_theme.corner_radius - 2}" ry="{active_theme.corner_radius - 2}"/>'
        f'<rect x="{margin - 10}" y="{margin - 6}" width="{inner_width}" height="2" fill="{active_theme.accent}" '
        'opacity="0.92" rx="1" ry="1"/>'
        f'<rect x="{margin - 10}" y="{header_rect_y}" width="{inner_width}" height="{line_height + 8}" '
        f'fill="{active_theme.header_fill}" rx="10" ry="10" opacity="0.98"/>'
        + "".join(text_nodes)
        + "</svg>"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")


def extract_markdown_table(text: str) -> str | None:
    """Extract the first markdown table block from free text."""
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        if "|" not in lines[0] or "|" not in lines[1]:
            continue
        if _is_markdown_delimiter_row(lines[1]):
            return "\n".join(lines)
    return None


def strip_markdown_tables(text: str) -> str:
    """Remove markdown table blocks from a response, leaving only narrative text."""
    kept_blocks: list[str] = []
    for block in text.split("\n\n"):
        stripped = block.strip()
        if not stripped:
            continue
        lines = [line.rstrip() for line in stripped.splitlines() if line.strip()]
        if len(lines) >= 2 and "|" in lines[0] and "|" in lines[1] and _is_markdown_delimiter_row(lines[1]):
            continue
        kept_blocks.append(stripped)
    return "\n\n".join(kept_blocks).strip()


def rasterize_svg_to_png(
    *,
    svg_path: Path,
    output_path: Path,
    max_pixel_size: int = 2400,
) -> bool:
    """Rasterize one SVG file to PNG using macOS Quick Look when available."""
    qlmanage = shutil.which("qlmanage")
    if qlmanage is None:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                qlmanage,
                "-t",
                "-s",
                str(max_pixel_size),
                "-o",
                str(output_path.parent),
                str(svg_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    generated = output_path.parent / f"{svg_path.name}.png"
    if completed.returncode != 0 or not generated.exists():
        return False
    generated.replace(output_path)
    return output_path.exists()


def render_markdown_table_png(
    *,
    table_markdown: str,
    output_path: Path,
    title: str | None = None,
    theme: PresentationRenderTheme | None = None,
) -> bool:
    """Render one markdown table block directly to PNG using Pillow when available."""
    if Image is None or ImageDraw is None or ImageFont is None or ImageColor is None:
        return False

    active_theme = theme or PresentationRenderTheme()
    table_lines = _format_markdown_table_as_monospace(table_markdown)
    title_line = title.strip() if title else ""
    body_font = _load_monospace_font(active_theme.body_font_size)
    title_font = _load_monospace_font(active_theme.title_font_size)
    line_height = max(active_theme.line_height, _font_line_height(body_font) + 8)
    title_height = max(active_theme.title_font_size + 6, _font_line_height(title_font) + 4)
    max_len = max((len(line) for line in table_lines), default=0)
    margin = active_theme.margin
    char_width = max(_font_char_width(body_font), active_theme.char_width - 1.0)
    width = max(640, int(margin * 2 + max_len * char_width + 24))
    title_block_height = title_height + 16 if title_line else 0
    height = max(240, int(margin * 2 + title_block_height + len(table_lines) * line_height + 24))

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    _draw_vertical_gradient(
        draw=draw,
        size=(width, height),
        start_hex=active_theme.background_start,
        end_hex=active_theme.background_end,
    )

    panel_x = 14
    panel_y = 14
    panel_width = width - 28
    panel_height = height - 28
    _draw_rounded_rectangle(
        draw=draw,
        box=(panel_x + 10, panel_y + 10, panel_x + 10 + panel_width, panel_y + 10 + panel_height),
        radius=max(active_theme.corner_radius - 2, 0),
        fill=_rgba(active_theme.shadow_color, alpha=72),
    )
    _draw_rounded_rectangle(
        draw=draw,
        box=(panel_x, panel_y, panel_x + panel_width, panel_y + panel_height),
        radius=max(active_theme.corner_radius - 2, 0),
        fill=_rgba(active_theme.panel_fill),
        outline=_rgba(active_theme.panel_stroke),
        width=2,
    )
    _draw_rounded_rectangle(
        draw=draw,
        box=(panel_x, panel_y, panel_x + panel_width, panel_y + 16),
        radius=max(active_theme.corner_radius - 2, 0),
        fill=_rgba(active_theme.accent, alpha=42),
    )

    accent_y = margin - 6
    draw.rounded_rectangle(
        (margin - 10, accent_y, width - margin - 10, accent_y + 2),
        radius=1,
        fill=_rgba(active_theme.accent),
    )

    current_y = margin
    if title_line:
        draw.text(
            (margin, current_y),
            title_line,
            font=title_font,
            fill=_rgba(active_theme.title_color),
        )
        current_y += title_block_height

    header_rect_top = current_y - 6
    header_rect_bottom = current_y + line_height + 2
    _draw_rounded_rectangle(
        draw=draw,
        box=(margin - 10, header_rect_top, width - margin - 10, header_rect_bottom),
        radius=10,
        fill=_rgba(active_theme.header_fill),
    )

    for index, line in enumerate(table_lines):
        if index == 0:
            fill = _rgba(active_theme.header_color)
        elif index == 1:
            fill = _rgba(active_theme.divider_color)
        else:
            fill = _rgba(active_theme.text_color)
        draw.text((margin, current_y), line, font=body_font, fill=fill)
        current_y += line_height

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return output_path.exists()


def _format_markdown_table_as_monospace(table_markdown: str) -> list[str]:
    rows = [_split_markdown_row(line) for line in table_markdown.splitlines() if line.strip()]
    if len(rows) < 2:
        return [table_markdown.strip()]
    header = rows[0]
    body = rows[2:] if _is_markdown_delimiter_row(table_markdown.splitlines()[1]) else rows[1:]
    widths = [len(cell) for cell in header]
    for row in body:
        for index, cell in enumerate(row):
            if index >= len(widths):
                widths.append(len(cell))
            else:
                widths[index] = max(widths[index], len(cell))

    def format_row(cells: list[str]) -> str:
        padded = []
        for index, width in enumerate(widths):
            value = cells[index] if index < len(cells) else ""
            padded.append(value.ljust(width))
        return " | ".join(padded).rstrip()

    separator = "-+-".join("-" * width for width in widths)
    lines = [format_row(header), separator]
    for row in body:
        lines.append(format_row(row))
    return lines


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_markdown_delimiter_row(line: str) -> bool:
    normalized = line.replace("|", "").replace(":", "").replace("-", "").strip()
    return normalized == ""


def _load_monospace_font(size: int):
    if ImageFont is None:
        raise RuntimeError("Pillow is not available")
    candidates = (
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _font_line_height(font: Any) -> int:
    if hasattr(font, "getbbox"):
        left, top, right, bottom = font.getbbox("Ag")
        return max(bottom - top, 1)
    return max(font.getsize("Ag")[1], 1)


def _font_char_width(font: Any) -> float:
    sample = "MMMMMMMMMM"
    if hasattr(font, "getlength"):
        return max(float(font.getlength(sample)) / len(sample), 1.0)
    if hasattr(font, "getbbox"):
        left, top, right, bottom = font.getbbox(sample)
        return max(float(right - left) / len(sample), 1.0)
    return max(float(font.getsize(sample)[0]) / len(sample), 1.0)


def _draw_vertical_gradient(
    *,
    draw: Any,
    size: tuple[int, int],
    start_hex: str,
    end_hex: str,
) -> None:
    width, height = size
    start = _rgba(start_hex)
    end = _rgba(end_hex)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(
            int(start[channel] + (end[channel] - start[channel]) * ratio)
            for channel in range(4)
        )
        draw.line((0, y, width, y), fill=color)


def _draw_rounded_rectangle(
    *,
    draw: Any,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _rgba(color: str, *, alpha: int = 255) -> tuple[int, int, int, int]:
    if ImageColor is None:
        raise RuntimeError("Pillow is not available")
    red, green, blue = ImageColor.getrgb(color)
    return red, green, blue, alpha
