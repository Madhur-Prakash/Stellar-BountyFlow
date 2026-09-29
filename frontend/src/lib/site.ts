/** Static, public site metadata. Optional links render only when configured. */
const githubUrl = (import.meta.env.VITE_GITHUB_URL as string | undefined)?.trim()

export const SITE = {
  name: 'BountyFlow',
  tagline: 'Work gets done. Rewards move transparently.',
  githubUrl: githubUrl && /^https:\/\//.test(githubUrl) ? githubUrl : null,
  freighterUrl: 'https://www.freighter.app/',
  stellarUrl: 'https://stellar.org/',
  sorobanDocsUrl: 'https://developers.stellar.org/docs/build/smart-contracts/overview',
  friendbotUrl: 'https://laboratory.stellar.org/#account-creator?network=test',
} as const

/** The year in the footer's copyright line. Bump it with a release rather than reading the viewer's clock. */
export const COPYRIGHT_YEAR = 2026
