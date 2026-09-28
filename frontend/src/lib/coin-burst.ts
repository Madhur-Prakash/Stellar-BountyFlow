import { motionAllowed } from '@/hooks/useReducedMotion'
import { gsap } from '@/lib/gsap'

type Origin = Element | DOMRect | { x: number; y: number }

function centerOf(origin: Origin): { x: number; y: number } {
  if ('x' in origin && 'y' in origin && !('width' in origin)) return origin
  const rect = origin instanceof Element ? origin.getBoundingClientRect() : origin
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
}

/**
 * A burst of coins thrown up from `origin` that fall away under gravity (GSAP Physics2D). Reserved for the moments
 * money actually moves: escrow funded, reward released, refund returned. Decorative only (aria-hidden) and skipped
 * under reduced motion. `tone` picks the coin colour: `release` (green, money reaching a contributor) or `fund`.
 */
export async function burstCoins(origin: Origin, { count = 22, tone = 'fund' as 'fund' | 'release' } = {}) {
  if (!motionAllowed() || typeof document === 'undefined') return
  const { Physics2DPlugin } = await import('gsap/Physics2DPlugin')
  gsap.registerPlugin(Physics2DPlugin)

  const { x, y } = centerOf(origin)
  const layer = document.createElement('div')
  layer.setAttribute('aria-hidden', 'true')
  layer.className = 'bf-coin-layer'
  document.body.append(layer)

  const tl = gsap.timeline({ onComplete: () => layer.remove() })
  for (let i = 0; i < count; i++) {
    const coin = document.createElement('span')
    coin.className = `bf-coin bf-coin--${tone}`
    const size = gsap.utils.random(9, 16, 1)
    coin.style.width = coin.style.height = `${size}px`
    coin.style.left = `${x - size / 2}px`
    coin.style.top = `${y - size / 2}px`
    layer.append(coin)
    const life = gsap.utils.random(1.1, 1.7)
    tl.to(
      coin,
      {
        duration: life,
        ease: 'none',
        rotationY: gsap.utils.random(-720, 720),
        physics2D: {
          velocity: gsap.utils.random(320, 640),
          angle: gsap.utils.random(-155, -25),
          gravity: 1150,
          friction: 0.015,
        },
      },
      i * 0.012,
    ).to(coin, { autoAlpha: 0, duration: 0.3, ease: 'power1.in' }, i * 0.012 + life - 0.3)
  }
}
