# Design system

BountyFlow should read as a calm, professional product: a marketplace where people trust it with money. It
should not look like a showcase site. Information comes first, every screen shows real data, and motion is small
and functional.

## Foundations

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `background` | `#fafafa` | `#09090b` | Page canvas |
| `card` | `#ffffff` | `#131316` | Cards, panels, tables |
| `surface` | `#f4f4f5` | `#111113` | Table headers, inset areas, bands |
| `foreground` | `#18181b` | `#fafafa` | Text |
| `muted-foreground` | `#6b6b75` | `#a1a1aa` | Secondary text, labels |
| `border` / `input` | `#e4e4e7` | `#27272a` / `#2e2e33` | Hairlines, field borders |
| `primary` | `#3563e9` | `#3a62e4` | The one accent: primary actions, links, focus, active navigation |
| `success` | `#12733a` | `#4ade80` | Funded in escrow, paid, confirmed. Reserved for money that is really there |
| `warning` / `destructive` | amber / red | | Attention and errors only |

- **Type:** Inter Variable for the whole interface. IBM Plex Mono only for machine data (hashes, addresses,
  contract ids), through `MonoValue`. Use `.amount` for money and counts (tabular figures).
- **Scale:**
  - Page titles: `PageHeader`, 24–26px semibold.
  - Card and section titles: 15–16px semibold.
  - Body text in the app: 14px (`text-sm`).
  - Labels and meta: 12–13px (`text-xs`, `text-[0.8125rem]`) in muted-foreground.
  - Marketing headlines stay restrained: the landing H1 is at most about 52px, section headings about 30–36px.
- **Radius:** controls use `rounded-md` (8px), cards and panels `rounded-xl` (14px), badges 4px.
- **Elevation:** cards are `border bg-card shadow-soft`. Popovers and dialogs use `shadow-lift`. No coloured
  glows, no gradients on cards.
- **Density:** controls are 36px (`Button` default, `Input`, `Select`); small ones are 32px. Table rows are
  about 44px.

## Layout

- **Width:** `PageContainer` (96rem) on the public site. The workspace content area uses the same maximum width.
- **Canvas:** content sits on the off-white canvas inside white cards. Group related content in one card with
  a header row (title, optional description, actions on the right) instead of many small boxes.
- **Stats:** `StatGrid` + `StatTile`: one bordered strip with hairline dividers, a label above the number.
  Never show giant standalone numbers.
- **Lists of records:** tables (`components/ui/table`, `DataTable`) on desktop and stacked rows on mobile. Use
  cards only where the item is the content (a bounty card in a grid of results).
- **Empty, loading and error states:** `EmptyState`, boneyard skeletons (`Bones` / `QueryView skeleton`),
  `ErrorState`. Every data view has all three.
- **Status:** square tinted `Badge` tags (no pills, no coloured dots). Money states use the funding badge.

## Motion

Motion explains something or answers an action. It stays calm and never gets in the way of reading.

- **Everywhere:**
  - the route fade (`AnimatedOutlet`, a few px, about 0.3s)
  - Radix open/close animations on dialogs, menus, popovers and sheets
  - hover and focus colour transitions (150–200ms)
  - the theme-switch reveal
  - boneyard skeleton shimmer
- **Public site only:**
  - Lenis smooth wheel scrolling.
  - The two scroll stories on the landing and How it works pages. "How a bounty moves" walks through both
    tracks and hands off between them; the escrow diagram draws itself state by state. Each is a tall section
    with a sticky stage (`useScrollStory`), scrubbed by GSAP.
  - The hero preview: it cycles through the top open rewards (pauses on hover or focus), counts its reward up
    and fills its lifecycle bar.
  - Two decorative Three.js scenes (`components/three`): the dotted payments globe behind the hero card and the
    ledger field behind the closing call to action. They are lazy-loaded on large screens only, paused off
    screen, and hidden from assistive technology.
- **Not used:** parallax, split-text headline reveals, drag-and-throw objects, fade-ups on every section,
  confetti or coin bursts, hover lifts on cards, glossy "ball" markers.
- **Reduced motion:** everything respects `prefers-reduced-motion`. The scroll stories become static lists and
  a static diagram, and the 3D scenes render a single still frame.

## Writing

Sentence case, plain verbs, and the user's words, not the system's. Buttons say what happens ("Post a bounty",
"Fund escrow"). Every figure on screen comes from the API. There is no invented or placeholder data anywhere.
