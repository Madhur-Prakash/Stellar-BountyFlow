import { PenLine } from 'lucide-react'
import { useRef, useState } from 'react'

import { PageContainer } from '@/components/layout/PageContainer'
import { Reveal } from '@/components/motion/Reveal'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { motionAllowed, useReducedMotion } from '@/hooks/useReducedMotion'
import { useScrollEngineReady } from '@/hooks/useSmoothScroll'
import { gsap, ScrollTrigger, useGSAP } from '@/lib/gsap'
import { scrollToY } from '@/lib/scroll'
import { cn } from '@/lib/utils'

import { CONTRIBUTOR_STEPS, REQUESTER_STEPS, type Step } from './howItWorksData'
import { SectionHeading } from './SectionHeading'

const TRACKS = [
  { id: 'requester', title: 'When you post work', steps: REQUESTER_STEPS },
  { id: 'contributor', title: 'When you do the work', steps: CONTRIBUTOR_STEPS },
] as const
const HEADING = {
  title: 'How a bounty moves',
  description:
    'The same bounty seen from both sides. Only the steps marked “Signed in your wallet” ask your wallet to sign anything.',
}

/* Scroll story, in timeline units: one per requester step, the handoff between the two tracks, one per
   contributor step. */
const REQ = REQUESTER_STEPS.length
const CON = CONTRIBUTOR_STEPS.length
const HANDOFF = 1.6
const UNITS = REQ + HANDOFF + CON

/** Which track and step a point in the story corresponds to. */
function positionAt(progress: number): { track: 0 | 1; step: number } {
  const t = progress * UNITS
  if (t < REQ) return { track: 0, step: Math.min(REQ - 1, Math.floor(t)) }
  if (t < REQ + HANDOFF / 2) return { track: 0, step: REQ - 1 }
  if (t < REQ + HANDOFF) return { track: 1, step: 0 }
  return { track: 1, step: Math.min(CON - 1, Math.floor(t - REQ - HANDOFF)) }
}

/** Where in the story (0–1) a given step sits, so clicking a step can scroll to it. */
function progressOf(track: 0 | 1, step: number): number {
  return ((track === 0 ? step : REQ + HANDOFF + step) + 0.5) / UNITS
}

function SignedNote() {
  return (
    <span className="ml-2 inline-flex items-center gap-1 align-middle text-sm font-normal text-primary-emphasis">
      <PenLine className="size-3.5" aria-hidden />
      Signed in your wallet
    </span>
  )
}

/** Small screens and reduced motion: both tracks as plain numbered lists. */
function StaticTrack({ id, title, steps }: { id: string; title: string; steps: readonly Step[] }) {
  return (
    <div>
      <h3 id={id} className="text-lg font-semibold">
        {title}
      </h3>
      <Reveal as="ol" aria-labelledby={id} className="mt-6">
        {steps.map((step, i) => (
          <li
            key={step.title}
            className="relative grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-4 pb-8 last:pb-0"
          >
            {i < steps.length - 1 && (
              <span className="absolute top-9 bottom-1 left-[1.0625rem] w-px bg-border" aria-hidden />
            )}
            <span className="amount flex size-9 items-center justify-center rounded-full border bg-background text-base">
              {i + 1}
            </span>
            <div className="pt-1.5">
              <p className="font-medium">
                {step.title}
                {step.signed && <SignedNote />}
              </p>
              <p className="mt-1.5 max-w-prose text-[0.9375rem] leading-relaxed text-muted-foreground">
                {step.text}
              </p>
            </div>
          </li>
        ))}
      </Reveal>
    </div>
  )
}

/** One track's steps with its progress rail. Blue for the requester's side, green for the contributor's. */
function TrackSteps({
  index,
  active,
  step,
  onPick,
}: {
  index: 0 | 1
  active: boolean
  step: number
  onPick: (step: number) => void
}) {
  const track = TRACKS[index]
  const blue = index === 0
  return (
    <div data-track={index} className="relative col-start-1 row-start-1 pl-14">
      <span data-rail aria-hidden className="absolute top-3 bottom-3 left-4.75 w-px bg-border">
        <span
          data-fill
          className={cn('absolute inset-0 origin-top scale-y-0', blue ? 'bg-primary' : 'bg-success')}
        />
      </span>
      <ol>
        {track.steps.map((s, i) => {
          const state = !active ? 'idle' : i < step ? 'done' : i === step ? 'active' : 'next'
          return (
            <li
              key={s.title}
              data-step
              data-state={state}
              onClick={() => onPick(i)}
              className="group relative -mx-3 cursor-pointer rounded-xl px-3 py-4 transition-[background-color,opacity] duration-500 hover:bg-muted/70 data-[state=next]:opacity-40 data-[state=next]:hover:opacity-100"
            >
              <span
                className={cn(
                  'amount absolute top-4 -left-11 flex size-10 items-center justify-center rounded-full border bg-background text-base transition-[transform,background-color,border-color,color] duration-500 group-hover:scale-110',
                  state === 'active' &&
                    (blue
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-success bg-success text-success-foreground'),
                  state === 'done' &&
                    (blue ? 'border-primary text-primary-emphasis' : 'border-success text-success'),
                )}
              >
                {i + 1}
              </span>
              <p className="pt-1.5 text-lg font-medium">
                {s.title}
                {s.signed && <SignedNote />}
              </p>
              <p className="mt-1.5 max-w-prose leading-relaxed text-muted-foreground">{s.text}</p>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

/**
 * Large screens with motion: the section stays pinned until the whole story has played. Scrolling walks through
 * the requester's steps (blue), then hands off: those steps lift away, the track switch slides across, and the
 * contributor's steps (green) rise in. The step counter sits under the switch, next to the heading. Everything is
 * scrubbed, so scrolling back plays it in reverse. Steps can be pointed at and clicked.
 */
function PinnedStory() {
  const stage = useRef<HTMLDivElement>(null)
  const trigger = useRef<ScrollTrigger | null>(null)
  const positionRef = useRef<{ track: 0 | 1; step: number }>({ track: 0, step: 0 })
  const [position, setPosition] = useState<{ track: 0 | 1; step: number }>({ track: 0, step: 0 })
  const engine = useScrollEngineReady()

  useGSAP(
    () => {
      const el = stage.current
      // Wait for the page's scroll engine: the pin must be created against the engine it will live with.
      if (!el || engine === null) return
      const q = gsap.utils.selector(el)
      const [reqTrack, conTrack] = [q('[data-track="0"]')[0], q('[data-track="1"]')[0]]
      const reqSteps = Array.from(reqTrack.querySelectorAll<HTMLElement>('[data-step]'))
      const conSteps = Array.from(conTrack.querySelectorAll<HTMLElement>('[data-step]'))
      const [reqFill, conFill] = [
        reqTrack.querySelector('[data-fill]'),
        conTrack.querySelector('[data-fill]'),
      ]
      const [reqRail, conRail] = [
        reqTrack.querySelector('[data-rail]'),
        conTrack.querySelector('[data-rail]'),
      ]
      const indicator = q('[data-indicator]')[0]
      const buttons = q('[data-track-button]') as HTMLElement[]

      gsap.set(conSteps, { autoAlpha: 0, yPercent: 45 })
      gsap.set(conRail, { autoAlpha: 0 })
      gsap.set(indicator, { x: 0, width: () => buttons[0].offsetWidth })

      const tl = gsap.timeline({ defaults: { ease: 'none' }, paused: true })

      // The requester's rail fills step by step.
      tl.fromTo(reqFill, { scaleY: 0 }, { scaleY: 1, duration: REQ }, 0)

      // Handoff: the requester's steps lift away, the track switch slides across, the contributor's steps rise.
      tl.to(
        reqSteps,
        { autoAlpha: 0, yPercent: -45, stagger: 0.07, duration: 0.55, ease: 'power1.in' },
        REQ + 0.05,
      )
        .to(reqRail, { autoAlpha: 0, duration: 0.35 }, REQ + 0.3)
        .to(
          indicator,
          {
            x: () => buttons[1].offsetLeft - buttons[0].offsetLeft,
            width: () => buttons[1].offsetWidth,
            duration: 0.7,
            ease: 'power2.inOut',
          },
          REQ + 0.45,
        )
        .to(conRail, { autoAlpha: 1, duration: 0.3 }, REQ + 0.9)
        .to(
          conSteps,
          { autoAlpha: 1, yPercent: 0, stagger: 0.07, duration: 0.55, ease: 'power1.out' },
          REQ + 0.85,
        )

      // The contributor's rail fills step by step.
      tl.fromTo(conFill, { scaleY: 0 }, { scaleY: 1, duration: CON }, REQ + HANDOFF)

      // A standalone trigger drives the timeline: killing it with revert unwraps its pin spacer, so re-creating
      // the story (a new scroll engine, a remount) never nests spacers.
      const st = ScrollTrigger.create({
        animation: tl,
        trigger: el,
        start: 'top top+=64',
        end: () => `+=${Math.round(window.innerHeight * 0.4 * UNITS)}`,
        pin: true,
        pinSpacing: true,
        scrub: 0.6,
        anticipatePin: 1,
        invalidateOnRefresh: true,
        onUpdate: (self) => {
          const next = positionAt(self.progress)
          const prev = positionRef.current
          if (prev.track === next.track && prev.step === next.step) return
          positionRef.current = next
          setPosition(next)
        },
      })
      trigger.current = st
      return () => {
        st.kill(true)
        trigger.current = null
      }
    },
    { scope: stage, dependencies: [engine], revertOnUpdate: true },
  )

  const scrollToProgress = (p: number) => {
    const st = trigger.current
    if (st) scrollToY(st.start + (st.end - st.start) * p)
  }

  const active = TRACKS[position.track]

  return (
    // The pinned element is a plain block: ScrollTrigger turns pin spacing off when the pin's parent is a flex
    // container, and a pin spacer copies the display of what it wraps.
    <div ref={stage}>
      <div className="flex min-h-[calc(100svh-4rem)] items-center py-14">
        <PageContainer className="grid w-full grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)] gap-16">
          <div className="flex flex-col">
            <SectionHeading id="how-title" {...HEADING} />
            <div
              className="relative isolate mt-10 inline-flex w-fit gap-1 rounded-xl border bg-surface p-1"
              role="group"
              aria-label="Track"
            >
              <span
                data-indicator
                aria-hidden
                className="absolute inset-y-1 left-1 -z-10 rounded-lg bg-foreground"
              />
              {TRACKS.map((t, i) => (
                <button
                  key={t.id}
                  type="button"
                  data-track-button
                  aria-pressed={position.track === i}
                  onClick={() => scrollToProgress(i === 0 ? 0 : (REQ + HANDOFF) / UNITS + 0.001)}
                  className={cn(
                    'rounded-lg px-4 py-2.5 text-sm font-medium transition-colors duration-300',
                    position.track === i ? 'text-background' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {t.title}
                </button>
              ))}
            </div>
            <p className="mt-10 flex items-center gap-4 text-sm text-muted-foreground" aria-live="polite">
              <span
                key={`${position.track}-${position.step}`}
                className={cn(
                  'amount inline-block animate-in text-[4.5rem] leading-none duration-300 fade-in-0 slide-in-from-bottom-2',
                  position.track === 0 ? 'text-foreground' : 'text-success',
                )}
              >
                {String(position.step + 1).padStart(2, '0')}
              </span>{' '}
              <span className="leading-snug">
                <span className="block">of {active.steps.length} steps</span>{' '}
                <span className="block font-medium text-foreground">
                  {position.track === 0 ? 'when you post work' : 'when you do the work'}
                </span>
              </span>
            </p>
          </div>

          <div className="relative grid self-center" aria-hidden>
            <TrackSteps
              index={0}
              active={position.track === 0}
              step={position.step}
              onPick={(i) => scrollToProgress(progressOf(0, i))}
            />
            <TrackSteps
              index={1}
              active={position.track === 1}
              step={position.step}
              onPick={(i) => scrollToProgress(progressOf(1, i))}
            />
          </div>

          {/* The visual lists are decorative; this is the same story for screen readers. */}
          <div className="sr-only">
            {TRACKS.map((t) => (
              <div key={t.id}>
                <h3>{t.title}</h3>
                <ol>
                  {t.steps.map((s) => (
                    <li key={s.title}>
                      {s.title}
                      {s.signed ? ' (signed in your wallet)' : ''}: {s.text}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </PageContainer>
      </div>
    </div>
  )
}

export function HowItWorks() {
  const large = useMediaQuery('(min-width: 1024px)')
  const reduced = useReducedMotion()
  const pinned = large && !reduced && motionAllowed()

  return (
    <section id="how-it-works" aria-labelledby="how-title" className="border-b">
      {pinned ? (
        <PinnedStory />
      ) : (
        <PageContainer className="py-20 sm:py-24">
          <SectionHeading id="how-title" {...HEADING} />
          <div className="mt-12 grid gap-14 lg:grid-cols-2 lg:gap-20">
            {TRACKS.map((t) => (
              <StaticTrack key={t.id} id={`track-${t.id}`} title={t.title} steps={t.steps} />
            ))}
          </div>
        </PageContainer>
      )}
    </section>
  )
}
