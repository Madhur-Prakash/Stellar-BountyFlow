import { CircleAlert } from 'lucide-react'
import { Link } from 'react-router'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

import { ProsePage, type ProseSection } from './ProsePage'

const SECTIONS: ProseSection[] = [
  {
    id: 'about',
    title: 'About these terms',
    body: (
      <p>
        These terms describe how BountyFlow may be used. By creating an account you agree to them. If you
        don’t agree, please don’t use the service.
      </p>
    ),
  },
  {
    id: 'service',
    title: 'The service',
    body: (
      <>
        <p>
          BountyFlow is software that helps requesters publish paid tasks and contributors apply for and
          deliver them. Rewards are held and released by a Soroban smart contract on the Stellar network shown
          in the app.
        </p>
        <p>
          This is an experimental build intended primarily for Stellar Testnet. Test assets have no monetary
          value. Features may change or be removed without notice.
        </p>
      </>
    ),
  },
  {
    id: 'accounts',
    title: 'Accounts',
    body: (
      <ul>
        <li>You must provide accurate information and keep your password secure.</li>
        <li>You are responsible for activity under your account.</li>
        <li>We may suspend accounts that break these terms or put other users at risk.</li>
      </ul>
    ),
  },
  {
    id: 'wallets',
    title: 'Wallets and transactions',
    body: (
      <>
        <p>
          You control your wallet and keys. BountyFlow never holds your secret key and cannot sign on your
          behalf. Blockchain transactions you sign are final once confirmed; we cannot reverse them.
        </p>
        <p>
          You are responsible for checking the network, amount, and details shown before signing, and for any
          network fees.
        </p>
      </>
    ),
  },
  {
    id: 'conduct',
    title: 'Acceptable use',
    body: (
      <ul>
        <li>Don’t post illegal, harmful, deceptive, or infringing tasks or content.</li>
        <li>Don’t submit work you don’t have the right to deliver.</li>
        <li>Don’t attempt to disrupt the service, other users, or the contracts.</li>
        <li>Use the report feature for content that breaks these rules.</li>
      </ul>
    ),
  },
  {
    id: 'disputes',
    title: 'Disputes between users',
    body: (
      <p>
        Agreements about work are between requesters and contributors. BountyFlow provides a dispute process
        in which a moderator records a decision that the escrow arbiter can execute. We make reasonable
        efforts to be fair but do not guarantee any outcome.
      </p>
    ),
  },
  {
    id: 'liability',
    title: 'Disclaimers and liability',
    body: (
      <p>
        The service is provided “as is”, without warranties of any kind. Smart contracts and blockchain
        networks can fail or behave unexpectedly. To the extent permitted by law, the BountyFlow team is not
        liable for losses arising from use of the service, including lost funds, failed transactions, or
        unavailable networks.
      </p>
    ),
  },
  {
    id: 'changes',
    title: 'Changes',
    body: (
      <p>
        We may update these terms as the project evolves; the date at the top shows the latest version. See
        also our <Link to="/privacy">privacy notice</Link>.
      </p>
    ),
  },
]

export default function TermsPage() {
  return (
    <ProsePage
      eyebrow="Legal"
      title="Terms of use"
      intro="Plain-language terms for using BountyFlow."
      updated="September 2026"
      notice={
        <Alert variant="warning">
          <CircleAlert />
          <AlertTitle>Not legal advice</AlertTitle>
          <AlertDescription>
            These terms are written in plain language to explain how BountyFlow works. They are not legal
            advice.
          </AlertDescription>
        </Alert>
      }
      sections={SECTIONS}
    />
  )
}
