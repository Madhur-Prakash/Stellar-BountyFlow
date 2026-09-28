import { Benefits } from './landing/Benefits'
import { CallToAction } from './landing/CallToAction'
import { EscrowExplainer } from './landing/EscrowExplainer'
import { Faq } from './landing/Faq'
import { Hero } from './landing/Hero'
import { HowItWorks } from './landing/HowItWorks'
import { OpenBounties } from './landing/OpenBounties'
import { PlatformStats } from './landing/PlatformStats'
import { StackStrip } from './landing/StackStrip'

export default function LandingPage() {
  return (
    <>
      <Hero />
      <StackStrip />
      <PlatformStats />
      <OpenBounties />
      <HowItWorks />
      <EscrowExplainer />
      <Benefits />
      <Faq />
      <CallToAction />
    </>
  )
}
