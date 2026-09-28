import { Link } from 'react-router'

import { SITE } from '@/lib/site'

import { ProsePage, type ProseSection } from './ProsePage'

const ext = { target: '_blank', rel: 'noopener noreferrer nofollow' } as const

const GLOSSARY: [string, string][] = [
  ['Bounty', 'A paid task with a scope, acceptance criteria, deadline, and a reward per position.'],
  [
    'Position',
    'One slot for a contributor. A bounty with 3 positions can pay up to 3 people, one reward each.',
  ],
  ['Escrow', 'The Soroban smart contract that holds rewards until they are paid out or refunded.'],
  ['Funded', 'The full required amount (reward × positions) is confirmed in escrow on-chain.'],
  ['Stroop', 'The smallest unit of XLM: 0.0000001 XLM. Network fees are quoted in stroops.'],
  ['Transaction hash', 'The unique ID of a Stellar transaction. Paste it into an explorer to verify it.'],
  ['Arbiter', 'The address allowed to settle disputed escrow per a moderator’s recorded decision.'],
  ['Freighter', 'A browser-extension wallet for Stellar. It holds your keys and signs what you approve.'],
]

const SECTIONS: ProseSection[] = [
  {
    id: 'getting-started',
    title: 'Getting started',
    body: (
      <>
        <p>
          BountyFlow connects people who need work done (requesters) with people who do it (contributors).
        </p>
        <ol>
          <li>
            <Link to="/register">Create an account</Link> and confirm your email address. Email verification
            is required before you can publish a bounty.
          </li>
          <li>
            Complete onboarding: add skills and choose whether you want to request work, contribute, or both.
          </li>
          <li>
            Connect a Stellar wallet (see below). You need one to fund a bounty or to be assigned and paid.
          </li>
          <li>
            Requesters: create a draft, publish it, then fund the escrow. Contributors: browse the{' '}
            <Link to="/bounties">marketplace</Link> and apply.
          </li>
        </ol>
      </>
    ),
  },
  {
    id: 'wallets',
    title: 'Wallets & Freighter on Testnet',
    body: (
      <>
        <p>BountyFlow uses the Freighter browser extension. Your secret key never leaves Freighter.</p>
        <ol>
          <li>
            Install Freighter from{' '}
            <a href={SITE.freighterUrl} {...ext}>
              freighter.app
            </a>{' '}
            and create or import an account. Store your recovery phrase offline. BountyFlow will never ask for
            it.
          </li>
          <li>
            In Freighter’s settings, switch the network to <strong>Testnet</strong>.
          </li>
          <li>
            Fund your Testnet account with free test XLM using{' '}
            <a href={SITE.friendbotUrl} {...ext}>
              Friendbot
            </a>
            . Test XLM has no monetary value.
          </li>
          <li>
            In BountyFlow, click <strong>Connect wallet</strong> in the top bar, approve the connection, then
            choose <strong>Verify ownership</strong>. You’ll sign a challenge transaction that is never
            submitted to the network; it just proves the address is yours.
          </li>
        </ol>
        <p>
          If Freighter is on a different network than BountyFlow, we’ll warn you before any signature and
          block the transaction. Every transaction you review names the network it runs on before you sign.
        </p>
      </>
    ),
  },
  {
    id: 'escrow',
    title: 'Funding & escrow',
    body: (
      <>
        <p>
          Required escrow is <code>reward per position × positions</code>. Funding happens in three steps:
          BountyFlow prepares the transaction, you review and sign it in Freighter, and BountyFlow submits it
          and watches the network until it is confirmed.
        </p>
        <ul>
          <li>
            <strong>Funded</strong> is shown only after the network confirms the full amount is in escrow.
          </li>
          <li>
            <strong>Funding pending</strong> means a transaction was submitted but is not confirmed yet.
          </li>
          <li>
            <strong>Partially funded</strong> means less than the required amount is in escrow.
          </li>
        </ul>
        <p>
          Content can be edited while a bounty is unfunded; reward and positions can only change while it is a
          draft.
        </p>
      </>
    ),
  },
  {
    id: 'payouts',
    title: 'Payouts',
    body: (
      <>
        <p>
          When a requester approves a submission, BountyFlow creates a payment record. The requester then
          signs the payout, and the contract transfers one position’s reward to the contributor’s verified
          wallet.
        </p>
        <p>
          Every payout shows its status, amount, and transaction hash. Profile totals only include payouts
          confirmed on-chain.
        </p>
      </>
    ),
  },
  {
    id: 'disputes',
    title: 'Disputes',
    body: (
      <>
        <p>
          If a requester and an assigned contributor disagree, either can raise a dispute from the bounty and
          attach evidence. A moderator reviews it and records one of three outcomes: release to the
          contributor, refund to the requester, or dismiss.
        </p>
        <p>
          The decision is recorded off-chain first. If funds are in escrow, the arbiter wallet published in
          the app configuration then signs the matching contract call, which you can verify on the explorer.
        </p>
      </>
    ),
  },
  {
    id: 'fees',
    title: 'Fees',
    body: (
      <>
        <p>
          This build does not add a platform fee: the reward you fund is the reward that is paid out. Stellar
          charges a small network fee for each transaction (the base fee is 100 stroops, i.e. 0.00001 XLM, per
          operation), and Soroban contract calls add resource fees. The estimated fee is shown in the review
          step before you sign.
        </p>
      </>
    ),
  },
  {
    id: 'glossary',
    title: 'Glossary',
    body: (
      <dl className="grid gap-4 sm:grid-cols-2">
        {GLOSSARY.map(([term, def]) => (
          <div key={term} className="rounded-lg border bg-card p-4">
            <dt className="font-medium text-foreground">{term}</dt>
            <dd className="mt-1 text-sm text-muted-foreground">{def}</dd>
          </div>
        ))}
      </dl>
    ),
  },
]

const ACTIONS: { title: string; text: string; href: string; external?: boolean }[] = [
  { title: 'Browse bounties', text: 'Open work, with its reward and funding state.', href: '/bounties' },
  {
    title: 'Post a bounty',
    text: 'Write the scope, set a reward, fund it later.',
    href: '/app/bounties/create',
  },
  {
    title: 'Install Freighter',
    text: 'The wallet you sign every transaction with.',
    href: SITE.freighterUrl,
    external: true,
  },
  {
    title: 'Get test XLM',
    text: 'Fund a Testnet account with Friendbot.',
    href: SITE.friendbotUrl,
    external: true,
  },
]

/** The next steps a reader of the guide usually wants, kept beside the text on wide screens. */
function QuickActions() {
  return (
    <div>
      <h2 className="text-sm font-medium text-muted-foreground">Next steps</h2>
      <ul className="mt-3 divide-y rounded-xl border bg-card">
        {ACTIONS.map((a) => (
          <li key={a.title}>
            {a.external ? (
              <a
                href={a.href}
                {...ext}
                className="group block px-4 py-3.5 transition-colors hover:bg-muted/60"
              >
                <span className="text-sm font-medium group-hover:underline group-hover:underline-offset-4">
                  {a.title}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">{a.text}</span>
              </a>
            ) : (
              <Link to={a.href} className="group block px-4 py-3.5 transition-colors hover:bg-muted/60">
                <span className="text-sm font-medium group-hover:underline group-hover:underline-offset-4">
                  {a.title}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">{a.text}</span>
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function GuidePage() {
  return (
    <ProsePage
      title="Using BountyFlow"
      intro="How to post, fund, deliver, and get paid, and how the escrow works underneath."
      sections={SECTIONS}
      aside={<QuickActions />}
    />
  )
}
