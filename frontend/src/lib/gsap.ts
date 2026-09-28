import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { CustomEase } from 'gsap/CustomEase'
import { Flip } from 'gsap/Flip'
import { ScrollToPlugin } from 'gsap/ScrollToPlugin'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { SplitText } from 'gsap/SplitText'

/*
 * One GSAP setup for the whole app. The plugins every page may use are registered here; heavier, page-specific
 * ones (ScrollSmoother, Draggable + Inertia, Physics2D, DrawSVG, ScrambleText) are registered by the
 * component that needs them, so they stay in that route's chunk.
 */
gsap.registerPlugin(useGSAP, ScrollTrigger, ScrollToPlugin, SplitText, Flip, CustomEase)

// House eases. "settle": things arriving decelerate long and land softly. "snap": UI responses, firm and short.
CustomEase.create('bf-settle', 'M0,0 C0.12,0.72 0.18,1 1,1')
CustomEase.create('bf-snap', 'M0,0 C0.32,0 0.12,1 1,1')
gsap.defaults({ ease: 'bf-settle', duration: 0.6 })

// Mobile browsers resize the viewport when the address bar shows or hides; recalculating then causes jumps.
ScrollTrigger.config({ ignoreMobileResize: true })

export { Flip, gsap, ScrollToPlugin, ScrollTrigger, SplitText, useGSAP }

// Development only: inspect animations from the browser console (e.g. ScrollTrigger.getAll()).
if (import.meta.env.DEV && typeof window !== 'undefined') Object.assign(window, { gsap, ScrollTrigger })
