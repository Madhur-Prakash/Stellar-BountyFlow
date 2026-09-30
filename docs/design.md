# Design system

<!-- nav -->
[Documentation](README.md) &middot; [Readme](../README.md) &middot; [Development](development.md) &middot; [Testing](testing.md)
<!-- nav -->

BountyFlow reads as a calm, premium product: a marketplace people trust with money. Headlines are set large and
bold in Bricolage Grotesque over warm neutrals, with hairline grids and small monospace labels. Every screen shows
real data, and motion explains what happens to a bounty rather than decorating the page.

## Foundations

| Token | Light (default) | Dark | Use |
| --- | --- | --- | --- |
| `background` | `#fbfaf8` | `#0d0c0a` | Page canvas: warm paper / warm near-black |
| `card` | `#ffffff` | `#161511` | Cards, panels, tables |
| `surface` | `#f3f1ec` | `#12110e` | Table headers, inset areas, bands, footer |
| `foreground` | `#1b1a17` | `#f5f4ef` | Text |
| `muted-foreground` | `#69655c` | `#a8a396` | Secondary text, labels |
| `border` / `input` | `#e8e5de` / `#e1ddd4` | `#2b2924` / `#34312b` | Hairlines, field borders |
| `primary` | `#3563e9` | `#3a62e4` | Accent: app primary actions, links, focus, active navigation, progress |
| `success` | `#12733a` | `#4ade80` | Confirmation that something verified on-chain succeeded: a settled transaction, a passed check, a guarantee in prose. **Not** the funded/paid status tags — those use the blue accent with every other status, so a card never mixes two accent colours |
| `warning` / `destructive` | amber / red | | Attention and errors only |

- **Type:**
  - Headlines use Bricolage Grotesque Variable (`--font-display`, through `.font-display`): bold (700),
    optical sizing on, tracking about -0.025em. Large headlines may tighten to about -0.03em, never further.
  - Geist Variable is used for the interface and body text.
  - IBM Plex Mono is used for small section labels (`.label-mono`) and machine data (hashes, addresses and
    contract ids, through `MonoValue`).
  - Use `.amount` for money and counts (tabular figures).
- **Scale:**
  - Marketing hero H1: about 68–84px, bold.
  - Marketing section H2s: 32–44px, bold.
  - Page titles in the app: `PageHeader`, 28–32px, bold. `size="display"` (34–48px) is for document pages
    such as a bounty.
  - Card and section titles: 15–16px semibold.
  - Body text: 14px in the app (`text-sm`), 18–20px for marketing lead paragraphs.
  - Labels and meta: 12–13px in muted-foreground.
- **Buttons:**
  - The app uses `rounded-md` buttons with the blue primary.
  - Marketing calls to action are pills (`size="pill"`), with `variant="inverse"` (black on paper, white on
    night) for the main action and `variant="outline"` next to it.
- **Radius:** controls `rounded-md` (8px); cards and panels `rounded-xl` (14px); large framed panels
  `rounded-2xl`; badges 4px.
- **Elevation:** cards are `border bg-card shadow-soft`; popovers and dialogs use `shadow-lift`. No coloured glows.
- **Density:** controls are 36px on desktop and 40px on touch screens; table rows are about 44px.

## Marketing building blocks

`src/components/marketing` holds the pieces the public pages share:

- `AppWindow`: a framed window with the three title-bar dots, for showing the product itself (the hero's
  bounty board).
- `Atmosphere`: a large generated backdrop panel (`tone="dusk" | "dune" | "ember" | "night"`), used by the
  closing call to action and the 404 page. The landing stories sit on the plain canvas in ordinary cards; don't
  put them on backdrops. No photos: every backdrop is generated.
- `MonoLabel`: the small IBM Plex Mono label above a section heading. Use it sparingly.

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
- **Status:** square tinted `Badge` tags; money states use the funding badge. Board-style group headers (e.g.
  My bounties grouped by status) use a small status dot, the label and a mono count, like a board column.

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
  - The hero board: a framed "Bounty board" on the plain canvas, with one column per lifecycle stage.
    - As you scroll, the live bounty card moves from column to column (published, funded, in progress, in
      review, paid out) and its content updates. Later stages are worded as what will happen ("When funded, …").
    - The other columns show real bounties. A column with none says what happens at that stage and who acts,
      and the column holding the card shows nothing else.
    - The card cycles through the top three open rewards, and pauses on hover, on focus, or once the story has
      started.
  - Three Three.js scenes (`components/three`, lazy-loaded through `Scene`, paused off screen, hidden from
    assistive technology):
    - **Constellation:** a network of nodes behind the hero headline, masked away from the text. Payment
      pulses hop between nodes and light them up, and the network leans slightly towards the pointer. It is
      interactive: nodes light up under the pointer, and a press or tap anywhere over it sends a ripple of
      light outwards and launches payments from the nearest node. The canvas keeps `pointer-events: none` and
      hit-tests window events against its own box, so the headline stays selectable, the buttons stay
      clickable, and a touch still scrolls the page.
    - **Payments globe:** the dotted globe rising behind the "Built on the Stellar stack" strip, on large
      screens. It is interactive: drag it to turn it (it keeps some spin, then eases back), and click it to send
      a payment from that point to the nearest hubs. Vertical page scrolling still works on touch screens.
    - **Ledger field:** behind the closing call to action.
- **Not used:** parallax, split-text headline reveals, drag-and-throw objects, fade-ups on every section,
  confetti or coin bursts, hover lifts on cards, glossy "ball" markers.
- **Reduced motion:** everything respects `prefers-reduced-motion`. The scroll stories become static lists and
  a static diagram. The 3D scenes render a single still frame; the globe still turns while dragged, without
  inertia.

## Writing

Sentence case, plain verbs, and the user's words, not the system's. Buttons say what happens ("Post a bounty",
"Fund escrow"). Every figure on screen comes from the API. There is no invented or placeholder data anywhere.
