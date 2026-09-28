import type { CSSProperties } from 'react'

/*
 * The atmospheric panel behind the auth card, built from gradients only (no images): a dune-sand-to-sky dusk on
 * the light theme and a teal-to-moss forest dusk on the dark one, each under a fine film grain (SVG
 * feTurbulence). Purely decorative.
 */

const GRAIN = `url("data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 1.1 -0.2"/></filter><rect width="100%" height="100%" filter="url(#n)"/></svg>',
)}")`

const DUNES: CSSProperties = {
  backgroundImage: [
    // Low sun behind the haze, top right.
    'radial-gradient(38% 30% at 78% 16%, rgb(255 244 222 / 0.9), transparent 70%)',
    // Dune ridges, back to front, getting warmer and darker.
    'radial-gradient(95% 34% at 18% 74%, rgb(214 178 132 / 0.75), transparent 72%)',
    'radial-gradient(90% 32% at 86% 84%, rgb(196 150 102 / 0.8), transparent 70%)',
    'radial-gradient(120% 36% at 40% 104%, rgb(170 120 78 / 0.85), transparent 72%)',
    // Sky to sand.
    'linear-gradient(180deg, #c3d4dc 0%, #d9dcd6 30%, #e8dcc6 56%, #dcc19b 80%, #c9a57c 100%)',
  ].join(', '),
}

const FOREST: CSSProperties = {
  backgroundImage: [
    // Dusk light breaking through, top left.
    'radial-gradient(45% 38% at 16% 8%, rgb(120 176 160 / 0.42), transparent 72%)',
    // Canopy masses in teal and moss.
    'radial-gradient(60% 42% at 78% 28%, rgb(34 86 78 / 0.85), transparent 70%)',
    'radial-gradient(70% 45% at 24% 70%, rgb(48 84 52 / 0.8), transparent 72%)',
    'radial-gradient(65% 40% at 88% 92%, rgb(92 104 44 / 0.7), transparent 70%)',
    'radial-gradient(50% 30% at 50% 50%, rgb(14 44 42 / 0.7), transparent 70%)',
    'linear-gradient(165deg, #0f2d2e 0%, #11302b 38%, #1a3222 70%, #232e18 100%)',
  ].join(', '),
}

export function AuthBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 dark:hidden" style={DUNES} />
      <div className="absolute inset-0 hidden dark:block" style={FOREST} />
      <div
        className="absolute inset-0 opacity-[0.28] mix-blend-multiply dark:opacity-[0.3] dark:mix-blend-overlay"
        style={{ backgroundImage: GRAIN, backgroundSize: '220px 220px' }}
      />
      {/* A hairline inner edge so the panel reads as a frame in both themes. */}
      <div className="absolute inset-0 rounded-[inherit] shadow-[inset_0_0_0_1px_rgb(0_0_0/0.06)] dark:shadow-[inset_0_0_0_1px_rgb(255_255_255/0.06)]" />
    </div>
  )
}
