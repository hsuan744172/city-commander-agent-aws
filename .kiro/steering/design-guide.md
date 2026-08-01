---
inclusion: fileMatch
fileMatchPattern: "frontend/src/**"
---

# Paperclip Design Guide — City Commander Agent

This project follows the Paperclip Design system: a dense, keyboard-driven, dark-themed control plane UI.
Source: https://www.skills.sh/getpaperclipai/paperclip/design-guide

## 1. Design Principles

- **Dense but scannable.** Maximum information without clicks to reveal. Whitespace separates, not pads.
- **Keyboard-first.** Global shortcuts (Cmd+K, C, [, ]). Power users rarely touch the mouse.
- **Contextual, not modal.** Inline editing over dialog boxes. Dropdowns over page navigations.
- **Light theme.** Clean near-white background (#FBFEFD) with mint green primary. Accent colors for status/priority only. Text is the primary visual element.
- **Component-driven.** Prefer reusable components that capture style conventions. Build at the right abstraction — not too granular, not too monolithic.

## 2. Tech Stack

- React 19 + Vite
- Tailwind CSS v4 with CSS variables
- Inter font (Google Fonts)
- Lucide React icons (16px nav, 14px inline)
- `clsx` + `tailwind-merge` via `cn()` utility from `@/lib/utils`

## 3. Design Tokens

All tokens are defined as CSS variables in `frontend/src/index.css`. Light theme with custom palette.

### Colors — use semantic token names, never raw color values:

Core palette (from [realtimecolors.com](https://www.realtimecolors.com/?colors=061d17-fafefd-3bd9a3-9f8be9-ba56de&fonts=Inter-Inter)):
- Text: `#061E18` (dark green-black)
- Background: `#FBFEFD` (near-white, green tint)
- Primary: `#3AD9A2` (mint green)
- Secondary: `#A08BE9` (purple)
- Accent: `#BA56DE` (magenta-purple)

| Token | Usage |
|-------|-------|
| `--background` / `--foreground` | Page background and primary text |
| `--card` / `--card-foreground` | Card surfaces |
| `--primary` / `--primary-foreground` | Primary actions, emphasis (mint green) |
| `--secondary` / `--secondary-foreground` | Secondary surfaces (purple) |
| `--muted` / `--muted-foreground` | Subdued text, labels |
| `--accent` / `--accent-foreground` | Highlights, hyperlinks (magenta-purple) |
| `--destructive` | Destructive actions |
| `--border` | All borders |
| `--ring` | Focus rings |
| `--sidebar-*` | Sidebar-specific variants |
| `--chart-1` through `--chart-5` | Data visualization |

### Radius (Material 3 Corner Radius Scale)

Follows the [M3 shape system](https://m3.material.io/styles/shape/corner-radius-scale):

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-none` | 0px | Sharp edges |
| `--radius-xs` | 4px | Chips, small pills, inline badges |
| `--radius-sm` | 8px | Buttons, inputs, small components |
| `--radius-md` | 12px | Cards, dialogs (default `--radius`) |
| `--radius-lg` | 16px | Card containers, large components |
| `--radius-lg-increased` | 20px | Prominent cards |
| `--radius-xl` | 28px | Modals, bottom sheets |
| `--radius-xl-increased` | 32px | Large modals |
| `--radius-2xl` | 48px | Hero cards |
| `--radius-full` | 9999px | Avatars, status dots, FABs |

Use via `rounded-[var(--radius-sm)]` or Tailwind utilities mapped to the scale:
- `rounded-sm` → small inputs, badges
- `rounded-md` → buttons, inputs
- `rounded-lg` → cards, dialogs
- `rounded-xl` → large containers
- `rounded-full` → pills, avatars, status dots

### Shadows

Minimal shadows: `shadow-xs` (outline buttons), `shadow-sm` (cards). No heavy shadows.

## 4. Typography Scale

Use these exact patterns — do not invent new ones:

| Pattern | Classes | Usage |
|---------|---------|-------|
| Page title | `text-xl font-bold` | Top of pages |
| Section title | `text-lg font-semibold` | Major sections |
| Section heading | `text-sm font-semibold text-muted-foreground uppercase tracking-wide` | Section headers, sidebar |
| Card title | `text-sm font-medium` or `text-sm font-semibold` | Card headers, list items |
| Body | `text-sm` | Default body text |
| Muted | `text-sm text-muted-foreground` | Descriptions, secondary text |
| Tiny label | `text-xs text-muted-foreground` | Metadata, timestamps |
| Mono identifier | `text-xs font-mono text-muted-foreground` | IDs, CSS vars |
| Large stat | `text-2xl font-bold` | Dashboard metric values |
| Code/log | `font-mono text-xs` | Log output, code snippets |

## 5. Status & Priority Systems

### Status Colors (consistent across all entities)

| Status | Color | Entity types |
|--------|-------|-------------|
| active, completed, done | Green | Agents, incidents |
| running | Cyan | Active processes |
| paused | Orange | Paused operations |
| idle, pending | Yellow | Waiting states |
| failed, error, blocked | Red | Errors, blocked states |
| archived, cancelled | Neutral gray | Inactive |
| in_progress | Indigo | Active work |

### Severity Indicators (City Commander specific)

- Critical (A-level): red with `AlertTriangle` icon
- High (B-level): orange with `ArrowUp` icon
- Medium: yellow with `Minus` icon
- Low: blue with `ArrowDown` icon

## 6. Interactive Patterns

### Hover States
- Entity rows: `hover:bg-accent/50`
- Nav items: `hover:bg-accent/50 hover:text-accent-foreground`
- Active nav: `bg-accent text-accent-foreground`

### Focus
`focus-visible:ring-ring focus-visible:ring-[3px]`

### Disabled
`disabled:opacity-50 disabled:pointer-events-none`

## 7. Layout System

Three-zone layout:
```
┌──────────┬──────────────────────────────┬──────────────────────┐
│ Sidebar  │  Header / Alert Ticker       │                      │
│          ├──────────────────────────────┤  Properties panel    │
│          │  Main content (flex-1)       │  (optional)          │
└──────────┴──────────────────────────────┴──────────────────────┘
```

## 8. File Conventions

- Components: `frontend/src/components/{ComponentName}.jsx` — PascalCase
- Utilities: `frontend/src/lib/{name}.js`
- Styles: `frontend/src/index.css` — single token source

## 9. Common Mistakes to Avoid

- Using raw hex/rgb colors instead of CSS variable tokens
- Creating ad-hoc typography styles instead of using the established scale
- Hardcoding status colors instead of using semantic tokens
- Using `shadow-md` or heavier — keep shadows minimal (`xs`, `sm` only)
- Using `rounded-2xl` or larger — max is `rounded-xl` (except `rounded-full` for pills)
- Forgetting dark mode — always use semantic tokens, never hardcode light/dark values
- Using Tailwind palette classes (`bg-red-500`, `text-zinc-400`) — use semantic tokens instead
