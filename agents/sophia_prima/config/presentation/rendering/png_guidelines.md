# PNG Render Guidelines

Use these guidelines for rendered table and chart images intended for messaging surfaces such as Telegram.

## Visual Direction

- Aim for an editorial terminal-card look: clean, sharp, high-contrast, and slightly technical.
- Prefer a layered background over a flat fill.
- Use one strong accent color consistently rather than many competing accents.

## Background

- Use a dark slate or near-black base with a subtle gradient.
- Add a soft accent glow or highlight band near the top edge.
- Keep the background quiet enough that text remains dominant.

## Typography

- Prefer `JetBrains Mono` first.
- Use fallback stacks that preserve a developer-terminal feel:
  - `JetBrains Mono`
  - `SFMono-Regular`
  - `Menlo`
  - `Consolas`
  - `monospace`
- Title weight should be bold and slightly larger than the table body.
- Header rows should feel distinct through weight and color, not just separators.

## Color

- Body text should be bright and high-contrast.
- Header text should use the accent color or a lighter highlight tone.
- Divider lines should be visible but restrained.
- Avoid muddy grays and low-contrast borders.

## Layout

- Use generous outer padding so the content feels framed.
- Preserve consistent column alignment.
- Leave enough vertical rhythm between title, table header, and rows.
- Avoid cramped cards; widen the canvas before reducing font size too aggressively.

## Constraints

- Never sacrifice readability for decoration.
- Preserve exact values and labels from the underlying data.
- Use deterministic styling so the same input renders the same way.
