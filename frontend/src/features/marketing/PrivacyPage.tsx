import { ProseNote, ProsePage, type ProseSection } from './ProsePage'

const SECTIONS: ProseSection[] = [
  {
    id: 'what',
    title: 'What we collect',
    body: (
      <ul>
        <li>
          <strong>Account data:</strong> email, username, display name, password (stored as a hash), and
          optional profile details such as bio, skills, and links.
        </li>
        <li>
          <strong>Marketplace activity:</strong> bounties, applications, submissions, reviews, reports, and
          disputes you create.
        </li>
        <li>
          <strong>Wallet data:</strong> public Stellar addresses you link and the signed challenges proving
          ownership. We never collect secret keys or recovery phrases.
        </li>
        <li>
          <strong>Technical data:</strong> session records (creation time, last use, browser user agent) used
          to keep you signed in and let you revoke sessions.
        </li>
      </ul>
    ),
  },
  {
    id: 'public',
    title: 'What is public',
    body: (
      <>
        <p>
          Published bounties, your public profile (username, display name, bio, skills, links, verified wallet
          addresses, and marketplace stats), and contribution history are visible to anyone.
        </p>
        <p>
          Transactions on Stellar are public by design. Anyone can see the addresses and amounts involved in
          funding and payouts; this cannot be undone.
        </p>
      </>
    ),
  },
  {
    id: 'cookies',
    title: 'Cookies and storage',
    body: (
      <p>
        We use strictly necessary cookies: <code>bf_access</code> and <code>bf_refresh</code> keep you signed
        in (HttpOnly, not readable by scripts) and <code>bf_csrf</code> protects forms against cross-site
        request forgery. Your theme preference is stored in your browser’s local storage. We don’t use
        advertising or tracking cookies.
      </p>
    ),
  },
  {
    id: 'use',
    title: 'How we use data',
    body: (
      <ul>
        <li>To run the marketplace: show bounties, route applications, and process reviews and payouts.</li>
        <li>To send account and activity emails (you can tune notification emails in settings).</li>
        <li>
          To keep the service safe: moderation, abuse prevention, and an audit log of sensitive actions.
        </li>
      </ul>
    ),
  },
  {
    id: 'rights',
    title: 'Your choices',
    body: (
      <p>
        You can edit your profile, unlink wallets, revoke sessions, and change notification preferences at any
        time from your settings. To request deletion of your account data, contact the project maintainers.
        On-chain transactions cannot be deleted.
      </p>
    ),
  },
]

export default function PrivacyPage() {
  return (
    <ProsePage
      eyebrow="Legal"
      title="Privacy notice"
      intro="What BountyFlow stores, what is public, and what never leaves your wallet."
      updated="September 2026"
      notice={
        <ProseNote title="Not legal advice">
          This notice explains in plain language how BountyFlow handles your data. It is not legal advice.
        </ProseNote>
      }
      sections={SECTIONS}
    />
  )
}
