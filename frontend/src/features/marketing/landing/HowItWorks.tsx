import { BriefcaseBusiness, PenLine, UserRound, type LucideIcon } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'

import { PageContainer } from '@/components/layout/PageContainer'
import { useScrollStory, useScrollStoryEnabled, type ScrollStoryTools } from '@/hooks/useScrollStory'
import { scrollToY } from '@/lib/scroll'
import { cn } from '@/lib/utils'

import { CONTRIBUTOR_STEPS, REQUESTER_STEPS, type Step } from './howItWorksData'
import { SECTION, SectionHeading } from './SectionHeading'

type Track = { id: string; title: string; icon: LucideIcon; steps: readonly Step[] }

const TRACKS: [Track, Track] = [
  { id: 'requester', title: 'When you post work', icon: BriefcaseBusiness, steps: REQUESTER_STEPS },
  { id: 'contributor', title: 'When you do the work', icon: UserRound, steps: CONTRIBUTOR_STEPS },
]

const HEADING = {
  title: 'How a bounty moves',
  description: 'The same bounty from both sides, from posting the work to the payout.',
}

/* The scroll story in timeline units: one per requester step, the handoff, one per contributor step. */
const REQ = REQUESTER_STEPS.length
const CON = CONTRIBUTOR_STEPS.length
const HANDOFF = 1.2
const UNITS = REQ + HANDOFF + CON

type Position = { track: 0 | 1; step: number }

/** Which track and step a point in the story (0–1) is on. */
function positionAt(progress: number): Position {
  const t = progress * UNITS
  if (t < REQ) return { track: 0, step: Math.min(REQ - 1, Math.floor(t)) }
  if (t < REQ + HANDOFF / 2) return { track: 0, step: REQ - 1 }
  if (t < REQ + HANDOFF) return { track: 1, step: 0 }
  return { track: 1, step: Math.min(CON - 1, Math.floor(t - REQ - HANDOFF)) }
}

/** Where in the story (0–1) a step sits, so a click can scroll to it. */
function progressOf(track: 0 | 1, step: number): number {
  return ((track === 0 ? step : REQ + HANDOFF + step) + 0.5) / UNITS
}

function SignedNote() {
  return (
    <span className="ml-2 inline-flex items-center gap-1 align-middle text-xs font-normal text-primary-emphasis">
      <PenLine className="size-3" aria-hidden />
      Signed in your wallet
    </span>
  )
}

function TrackHeader({ track, meta, headingId }: { track: Track; meta?: string; headingId?: string }) {
  const Icon = track.icon
  return (
    <div className="flex items-center gap-3 border-b px-5 py-4">
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="size-4" aria-hidden />
      </span>
      <h3 id={headingId} className="text-[0.9375rem] font-semibold">
        {track.title}
      </h3>
      <span className="ml-auto text-xs text-muted-foreground">{meta ?? `${track.steps.length} steps`}</span>
    </div>
  )
}

/** Static list of a track's steps: small screens and reduced motion. */
function StaticTrack({ track }: { track: Track }) {
  const headingId = `track-${track.id}`
  return (
    <div className="rounded-xl border bg-card shadow-soft">
      <TrackHeader track={track} headingId={headingId} />
      <ol aria-labelledby={headingId} className="px-5 py-2">
        {track.steps.map((step, i) => (
          <li key={step.title} className="relative grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 py-3.5">
            {i < track.steps.length - 1 && (
              <span aria-hidden className="absolute top-11 bottom-0 left-3.25 w-px bg-border" />
            )}
            <span
              aria-hidden
              className="amount flex size-7 items-center justify-center rounded-full border bg-background text-xs"
            >
              {i + 1}
            </span>
            <div className="pt-0.5">
              <p className="text-sm font-medium">
                {step.title}
                {step.signed && <SignedNote />}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{step.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

/** One track's steps in the story card. Their states come from React; only the rail fill is scrubbed. */
function StoryTrack({
  index,
  position,
  onPick,
}: {
  index: 0 | 1
  position: Position
  onPick: (step: number) => void
}) {
  const track = TRACKS[index]
  const active = position.track === index
  return (
    <div data-story-track={index} className="col-start-1 row-start-1">
      <div className="relative px-5 py-3">
        <span aria-hidden className="absolute top-8 bottom-8 left-8.75 w-px bg-border">
          <span data-rail-fill className="absolute inset-0 origin-top scale-y-0 bg-primary" />
        </span>
        <ol>
          {track.steps.map((s, i) => {
            const state = !active
              ? 'idle'
              : i < position.step
                ? 'done'
                : i === position.step
                  ? 'active'
                  : 'next'
            return (
              <li
                key={s.title}
                data-step
                data-state={state}
                onClick={() => onPick(i)}
                className={cn(
                  'relative grid cursor-pointer grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 rounded-lg px-2 py-3 transition-colors duration-300',
                  state === 'active' ? 'bg-primary/6' : 'hover:bg-muted/60',
                )}
              >
                <span
                  className={cn(
                    'amount relative z-10 flex size-7 items-center justify-center rounded-full border text-xs transition-colors duration-300',
                    state === 'active' && 'border-primary bg-primary text-primary-foreground',
                    state === 'done' && 'border-primary bg-card text-primary-emphasis',
                    (state === 'next' || state === 'idle') && 'bg-card text-muted-foreground',
                  )}
                >
                  {i + 1}
                </span>
                <div className="pt-0.5">
                  <p
                    className={cn(
                      'text-sm font-medium transition-colors duration-300',
                      state === 'next' ? 'text-muted-foreground' : 'text-foreground',
                    )}
                  >
                    {s.title}
                    {s.signed && <SignedNote />}
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{s.text}</p>
                </div>
              </li>
            )
          })}
        </ol>
      </div>
    </div>
  )
}

/**
 * The scrubbed parts of the story: each track's rail fills step by step, the requester's steps lift away at the
 * handoff while the contributor's rise in, and the progress bar advances. GSAP only animates these wrappers and
 * fills; the step states are React's, so the two never fight over the same styles.
 */
function buildTimeline({ gsap }: ScrollStoryTools, root: HTMLElement) {
  const q = gsap.utils.selector(root)
  const reqTrack = q('[data-story-track="0"]')[0]
  const conTrack = q('[data-story-track="1"]')[0]
  const reqFill = reqTrack.querySelector('[data-rail-fill]')
  const conFill = conTrack.querySelector('[data-rail-fill]')
  const progress = q('[data-story-progress]')

  gsap.set(conTrack, { autoAlpha: 0, yPercent: 8 })
  const tl = gsap.timeline({ defaults: { ease: 'none' } })
  tl.fromTo(progress, { scaleX: 0 }, { scaleX: 1, duration: UNITS }, 0)
    .fromTo(reqFill, { scaleY: 0 }, { scaleY: 1, duration: REQ - 0.5 }, 0.25)
    .to(reqTrack, { autoAlpha: 0, yPercent: -8, duration: HANDOFF * 0.55, ease: 'power1.in' }, REQ)
    .to(
      conTrack,
      { autoAlpha: 1, yPercent: 0, duration: HANDOFF * 0.55, ease: 'power1.out' },
      REQ + HANDOFF * 0.45,
    )
    .fromTo(conFill, { scaleY: 0 }, { scaleY: 1, duration: CON - 0.5 }, REQ + HANDOFF + 0.25)
  return tl
}

/** Large screens with motion: the section stays in view while the story plays with the scroll. */
function StoryMode() {
  const wrapper = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<Position>({ track: 0, step: 0 })
  const last = useRef(position)
  const onProgress = useCallback((p: number) => {
    const next = positionAt(p)
    if (next.track === last.current.track && next.step === last.current.step) return
    last.current = next
    setPosition(next)
  }, [])
  useScrollStory(wrapper, true, buildTimeline, onProgress)

  const scrollToProgress = (p: number) => {
    const el = wrapper.current
    if (!el) return
    const top = el.getBoundingClientRect().top + window.scrollY - 64
    const distance = el.offsetHeight - (window.innerHeight - 64)
    scrollToY(top + distance * Math.min(0.999, Math.max(0, p)))
  }

  const track = TRACKS[position.track]
  return (
    <div
      ref={wrapper}
      data-how-story
      className="relative"
      style={{ height: `calc(100svh - 4rem + ${Math.round(UNITS * 34)}svh)` }}
    >
      <div className="sticky top-16 flex h-[calc(100svh-4rem)] items-center">
        <PageContainer className="grid w-full grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] items-center gap-14">
          <div>
            <SectionHeading id="how-title" {...HEADING} />
            <div
              className="relative isolate mt-8 inline-grid w-fit grid-cols-2 gap-1 rounded-lg border bg-card p-1 shadow-soft"
              role="group"
              aria-label="Track"
            >
              <span
                aria-hidden
                className={cn(
                  'absolute inset-y-1 left-1 -z-10 w-[calc(50%-0.375rem)] rounded-md bg-foreground transition-transform duration-500 ease-out',
                  position.track === 1 && 'translate-x-[calc(100%+0.25rem)]',
                )}
              />
              {TRACKS.map((t, i) => (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={position.track === i}
                  onClick={() => scrollToProgress(i === 0 ? 0 : (REQ + HANDOFF) / UNITS + 0.001)}
                  className={cn(
                    'rounded-md px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors duration-300',
                    position.track === i ? 'text-background' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {t.title}
                </button>
              ))}
            </div>

            <p className="mt-8 flex items-center gap-4 text-sm text-muted-foreground" aria-live="polite">
              <span
                key={`${position.track}-${position.step}`}
                className="amount inline-block animate-in text-[3.5rem] leading-none text-foreground duration-300 fade-in-0 slide-in-from-bottom-2"
              >
                {String(position.step + 1).padStart(2, '0')}
              </span>{' '}
              <span className="leading-snug">
                <span className="block">of {track.steps.length} steps</span>{' '}
                <span className="block font-medium text-foreground">
                  {position.track === 0 ? 'when you post work' : 'when you do the work'}
                </span>
              </span>
            </p>
            <div aria-hidden className="mt-6 h-1 w-full max-w-sm overflow-hidden rounded-full bg-muted">
              <span
                data-story-progress
                className="block h-full origin-left scale-x-0 rounded-full bg-primary"
              />
            </div>
          </div>

          <div className="rounded-xl border bg-card shadow-lift">
            <div aria-hidden>
              <TrackHeader track={track} meta={`Step ${position.step + 1} of ${track.steps.length}`} />
            </div>
            <div className="grid" aria-hidden>
              <StoryTrack index={0} position={position} onPick={(i) => scrollToProgress(progressOf(0, i))} />
              <StoryTrack index={1} position={position} onPick={(i) => scrollToProgress(progressOf(1, i))} />
            </div>
            {/* The visual story is decorative; this is the same content for screen readers. */}
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
          </div>
        </PageContainer>
      </div>
    </div>
  )
}

/** Both sides of a bounty, step by step. Only the steps marked as signed ask the wallet for anything. */
export function HowItWorks({ className }: { className?: string }) {
  const story = useScrollStoryEnabled('1024px')
  return (
    <section
      id="how-it-works"
      aria-labelledby="how-title"
      className={cn(story ? 'py-4' : SECTION, className)}
    >
      {story ? (
        <StoryMode />
      ) : (
        <PageContainer>
          <SectionHeading id="how-title" {...HEADING} />
          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            {TRACKS.map((t) => (
              <StaticTrack key={t.id} track={t} />
            ))}
          </div>
        </PageContainer>
      )}
    </section>
  )
}
