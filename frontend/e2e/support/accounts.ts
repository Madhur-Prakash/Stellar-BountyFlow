/**
 * Accounts created by the backend seed. They are ordinary accounts that sign
 * in with email and password through the normal login form, like everyone
 * else. The backend gives all of them the same password (`SEED_USER_PASSWORD`,
 * default "BountyFlow!2026"); set E2E_SEED_PASSWORD when the stack under test
 * uses a different one.
 */
export const SEED_PASSWORD = process.env.E2E_SEED_PASSWORD ?? 'BountyFlow!2026'

export type SeededAccount = {
  username: string
  displayName: string
  email: string
  password: string
  role: 'USER' | 'MODERATOR' | 'ADMIN'
}

function seeded(
  username: string,
  displayName: string,
  email: string,
  role: SeededAccount['role'],
): SeededAccount {
  return { username, displayName, email, password: SEED_PASSWORD, role }
}

export const SEEDED_ACCOUNTS = {
  ada: seeded('ada-okafor', 'Ada Okafor', 'ada.okafor@bountyflow.test', 'USER'),
  kai: seeded('kai-tanaka', 'Kai Tanaka', 'kai.tanaka@bountyflow.test', 'USER'),
  morgan: seeded('morgan-reyes', 'Morgan Reyes', 'morgan.reyes@bountyflow.test', 'ADMIN'),
  priya: seeded('priya-nair', 'Priya Nair', 'priya.nair@bountyflow.test', 'MODERATOR'),
  nova: seeded('nova-labs', 'Nova Labs', 'nova.labs@bountyflow.test', 'USER'),
  river: seeded('river-chen', 'River Chen', 'river.chen@bountyflow.test', 'USER'),
  mira: seeded('mira-kovac', 'Mira Kovač', 'mira.kovac@bountyflow.test', 'USER'),
  sol: seeded('sol-adeyemi', 'Sol Adeyemi', 'sol.adeyemi@bountyflow.test', 'USER'),
} as const satisfies Record<string, SeededAccount>

/** Who plays which part in the specs. */
export const REQUESTER = SEEDED_ACCOUNTS.ada
export const CONTRIBUTOR = SEEDED_ACCOUNTS.kai
export const ADMIN = SEEDED_ACCOUNTS.morgan
export const MODERATOR = SEEDED_ACCOUNTS.priya
