import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * The backdrops behind framed product panels, drawn with layered gradients instead of photographs:
 * - `dusk`: deep teal into moss, like forest seen from the air;
 * - `dune`: evening sky over warm sand;
 * - `ember`: slate cloud catching a rust sunset;
 * - `night`: deep blue with a glow of the brand colour rising from below.
 * Each has a light version (the same scene on warm paper) and a dark one.
 */
export type AtmosphereTone = 'dusk' | 'dune' | 'ember' | 'night'

const LIGHT: Record<AtmosphereTone, string> = {
  dusk: [
    'radial-gradient(70% 65% at 12% 8%, rgb(118 178 168 / 0.5), transparent 70%)',
    'radial-gradient(55% 70% at 92% 95%, rgb(182 196 118 / 0.55), transparent 70%)',
    'radial-gradient(45% 45% at 62% 38%, rgb(150 196 182 / 0.35), transparent 70%)',
    'linear-gradient(160deg, #d6e7e2 0%, #dfeadf 45%, #e8ead2 100%)',
  ].join(', '),
  dune: [
    'radial-gradient(90% 55% at 70% 108%, rgb(226 184 128 / 0.7), transparent 70%)',
    'radial-gradient(60% 55% at 18% 0%, rgb(150 188 222 / 0.6), transparent 70%)',
    'radial-gradient(40% 30% at 85% 20%, rgb(255 255 255 / 0.6), transparent 70%)',
    'linear-gradient(180deg, #dfe9f1 0%, #e9ece8 48%, #eedfc6 100%)',
  ].join(', '),
  ember: [
    'radial-gradient(55% 60% at 82% 28%, rgb(238 160 124 / 0.55), transparent 70%)',
    'radial-gradient(50% 50% at 22% 85%, rgb(244 200 150 / 0.55), transparent 70%)',
    'radial-gradient(60% 50% at 8% 0%, rgb(172 184 228 / 0.6), transparent 70%)',
    'linear-gradient(135deg, #e5e6f2 0%, #efe3e3 45%, #f5dfcf 100%)',
  ].join(', '),
  night: [
    'radial-gradient(70% 80% at 50% 115%, rgb(53 99 233 / 0.26), transparent 70%)',
    'radial-gradient(40% 45% at 88% 0%, rgb(160 176 236 / 0.35), transparent 70%)',
    'linear-gradient(180deg, #eef1f8 0%, #e4e9f7 100%)',
  ].join(', '),
}

const DARK: Record<AtmosphereTone, string> = {
  dusk: [
    'radial-gradient(70% 60% at 12% 6%, rgb(58 132 124 / 0.55), transparent 70%)',
    'radial-gradient(60% 70% at 92% 96%, rgb(128 142 52 / 0.5), transparent 70%)',
    'radial-gradient(45% 40% at 60% 42%, rgb(34 88 76 / 0.55), transparent 70%)',
    'linear-gradient(160deg, #0a2023 0%, #0e2a26 40%, #183021 70%, #24311a 100%)',
  ].join(', '),
  dune: [
    'radial-gradient(90% 55% at 70% 108%, rgb(186 138 84 / 0.6), transparent 70%)',
    'radial-gradient(60% 50% at 18% 0%, rgb(70 108 146 / 0.45), transparent 70%)',
    'linear-gradient(180deg, #0f1a24 0%, #1a2833 42%, #382f25 74%, #5e4830 100%)',
  ].join(', '),
  ember: [
    'radial-gradient(55% 60% at 82% 28%, rgb(190 82 44 / 0.55), transparent 70%)',
    'radial-gradient(50% 50% at 22% 85%, rgb(200 128 70 / 0.35), transparent 70%)',
    'radial-gradient(60% 50% at 8% 0%, rgb(58 78 128 / 0.55), transparent 70%)',
    'linear-gradient(135deg, #121828 0%, #261f2f 40%, #432723 70%, #5f3120 100%)',
  ].join(', '),
  night: [
    'radial-gradient(70% 80% at 50% 115%, rgb(58 98 228 / 0.42), transparent 70%)',
    'radial-gradient(40% 45% at 88% 0%, rgb(110 130 210 / 0.16), transparent 70%)',
    'linear-gradient(180deg, #0b0e1a 0%, #0e142b 60%, #121a3c 100%)',
  ].join(', '),
}

/** Fine film grain: fractal noise, desaturated, tiled. Kept at low contrast so it reads as texture, not dirt. */
const GRAIN =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='g'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(%23g)'/></svg>\")"

/** Soft, cloud-like variation at a large scale, so the gradients read as light on terrain rather than a flat fill. */
const MOTTLE =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='900' height='900'><filter id='m'><feTurbulence type='fractalNoise' baseFrequency='0.0045 0.0065' numOctaves='5' seed='11' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(%23m)'/></svg>\")"

/**
 * An atmospheric backdrop panel: layered gradients, large soft mottling, film grain and a vignette, in light and
 * dark versions.
 * Put an `AppWindow` (or any framed content) inside. `backdrop` renders between the gradient and the grain,
 * for a decorative scene such as a WebGL canvas. Everything it draws is hidden from assistive technology.
 */
export function Atmosphere({
  tone = 'dusk',
  backdrop,
  grain = true,
  className,
  children,
}: {
  tone?: AtmosphereTone
  backdrop?: ReactNode
  grain?: boolean
  className?: string
  children?: ReactNode
}) {
  return (
    <div data-atmosphere={tone} className={cn('relative isolate overflow-hidden rounded-2xl', className)}>
      <div
        aria-hidden
        className="absolute inset-0 -z-30 dark:hidden"
        style={{ backgroundImage: LIGHT[tone] }}
      />
      <div
        aria-hidden
        className="absolute inset-0 -z-30 hidden dark:block"
        style={{ backgroundImage: DARK[tone] }}
      />
      {backdrop && (
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-20">
          {backdrop}
        </div>
      )}
      {grain && (
        <>
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 opacity-40 mix-blend-soft-light dark:opacity-55"
            style={{ backgroundImage: MOTTLE, backgroundSize: 'cover', backgroundPosition: 'center' }}
          />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 opacity-[0.22] mix-blend-multiply dark:opacity-[0.3] dark:mix-blend-soft-light"
            style={{ backgroundImage: GRAIN, backgroundSize: '220px 220px' }}
          />
        </>
      )}
      {/* A soft vignette so the edges settle into the page. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 rounded-[inherit] shadow-[inset_0_0_0_1px_rgb(27_26_23/0.06)] dark:shadow-[inset_0_0_140px_rgb(0_0_0/0.45),inset_0_0_0_1px_rgb(255_255_255/0.05)]"
      />
      {children}
    </div>
  )
}
