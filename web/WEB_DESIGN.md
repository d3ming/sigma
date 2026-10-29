# Web design base

Wire owns the visual base in [`tokens.css`](tokens.css): colors in light and dark, fonts, type scale, spacing, radii and
line weights. Other sites (Alpha) copy that file byte for byte. **Do not edit a copy.** To change a value, change it here;
copies are checked for drift against this file. Layout, components, navigation and information architecture belong to each
site, which builds them from these tokens. Wire's own are in `wire/site.py`.

## Colors

Every color is a `light-dark(light, dark)` pair, so one rule covers both themes. Use a token; never a hex value.

| Token | Use |
|---|---|
| `--base` | Page background. `--surface-1` to `--surface-3` step up from it: panels, controls and chips, selected or popover |
| `--border`, `--border-strong` | Hairlines and control borders; the strong one for a border that must read on a surface |
| `--text`, `--text-secondary`, `--text-muted` | Body and headings; supporting copy; labels, meta and placeholders |
| `--text-on-accent` | Text on an `--accent` fill |
| `--accent`, `--accent-soft` | The one electric color: hover, active, focus, marks. The soft form is a 12% wash |
| `--grid`, `--glow` | Dot grid and soft light behind the top of a page |
| `--positive`, `--negative`, `--warning` (+ `-muted`) | Meaning only (good, bad, stale), always beside a label or icon. Muted forms are fills |
| `--bucket-*` | Five category hues for charts and grouped data. A hue means one category and nothing else |

## Type

Fonts: `--font-sans` (Geist) for text, `--font-mono` (Geist Mono) for every reading, number and label,
`--font-display` (Unbounded) for the wordmark and page titles. Body is 1rem on a 1.6 line height.

| Token | Size | Use |
|---|---|---|
| `--text-title` / `--text-page` | 1.9rem / 1.5rem | Page title: reading page / dense app page |
| `--text-heading` | 1.32rem | Item and theme headings |
| `--text-lede`, `--text-section` | 1.2rem, 17px | Paragraph under a title; section title |
| `--text-row`, `--text-detail` | 15px, 13px | Row primary; row secondary and mono readings |
| `--text-caption`, `--text-micro` | 12px, 11px | Captions, nav, column heads; micro labels. Nothing is smaller |

## Spacing, radii, line weights

- Spacing is a 4px scale: `--space-1` to `--space-6` are 4, 8, 12, 16, 20, 24; `--space-8` is 32.
- Radii: `--radius-xs` 3px (chips, tags, focus rings), `--radius-sm` 4px (marks), `--radius-md` 6px (buttons, inputs),
  `--radius-lg` 8px (panels), `--radius-full` for pills.
- Line weights: `--line-1` 1px for dividers and borders; `--line-2` 2px for the active tab, quote rule, focus ring and header rule.
- Elevation is flat. `--shadow-2` and `--shadow-3` are for a menu or dialog that floats over content.

## Light and dark

- Both themes are first-class. Check every page in both before shipping.
- The user switch has three states: system, light, dark. System is the default. Set `data-theme="light"` or `"dark"` on
  `<html>`; for system, set nothing. Remember the choice in `localStorage` (wrapped in try/catch) and apply it in `<head>`
  before the stylesheet so the page never flashes. Wire's key is `wire-theme`; each site uses its own.
- Anything that needs the effective theme (an embed, a chart library) reads `data-theme`, and falls back to
  `matchMedia('(prefers-color-scheme: dark)')` when it is not `light` or `dark`.
- `light-dark()` needs Chrome 123, Safari 17.5 or Firefox 120 or later.

## Decisions

- Gradients and glow are allowed: the dot grid and glow behind the page top, and the accent rule across the header. Cards
  and tables stay flat.
- Sentence case for headings, buttons and navigation. Small uppercase mono with letter spacing (0.06 to 0.14em) is only for
  table column headers and micro labels.
  Wire's own site predates this rule: its nav and section headings are still uppercase mono.
- Fonts load through the site's own font loader. A site that uses a loader sets `--font-geist-sans`, `--font-geist-mono`
  and `--font-unbounded` to the family names it loaded; otherwise the plain names in `tokens.css` apply.
