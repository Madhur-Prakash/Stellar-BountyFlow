export type Step = { title: string; text: string; signed?: boolean }

export const REQUESTER_STEPS: Step[] = [
  {
    title: 'Describe the work',
    text: 'Write the scope, acceptance criteria, deadline, and reward per position. Drafts stay private until you publish.',
  },
  {
    title: 'Fund the escrow',
    text: 'Lock reward × positions in the Soroban escrow contract. The bounty shows as funded only after the network confirms the transaction.',
    signed: true,
  },
  {
    title: 'Pick contributors',
    text: 'Review applications and accept the people you want. You can also record the assignment on-chain, which protects their reward from a refund.',
  },
  {
    title: 'Review against your criteria',
    text: 'Approve a submission, ask for a revision, or reject it with a reason. Every decision is kept in the activity log.',
  },
  {
    title: 'Release the payout',
    text: 'The contract pays the contributor’s verified wallet. The transaction hash is public, so anyone can check it.',
    signed: true,
  },
]

export const CONTRIBUTOR_STEPS: Step[] = [
  {
    title: 'Find funded work',
    text: 'Filter by skill, reward, and deadline. “Funded only” shows bounties whose reward is already in escrow.',
  },
  {
    title: 'Verify your wallet',
    text: 'Connect Freighter and sign a one-time challenge that proves you own the address payouts go to. Nothing is sent to the network.',
    signed: true,
  },
  {
    title: 'Apply and deliver',
    text: 'Send a short proposal. Once you are accepted, submit the work with links the requester can review.',
  },
  {
    title: 'Get paid from escrow',
    text: 'When your submission is approved, the contract pays you directly. The payout appears in your history with its hash.',
  },
]
