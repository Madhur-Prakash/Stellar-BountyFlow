#!/usr/bin/env node
/**
 * Regenerates the boneyard skeletons in src/bones from the running app, using the real seeded data.
 *
 *   pnpm bones
 *
 * Needs the app (Vite dev server or the Docker frontend) on BONES_APP_URL (default http://localhost:5173) talking
 * to a seeded API. Signed-in pages are captured with sessions of seeded accounts: the requester (Ada) for the
 * workspace, the contributor (Kai) for application and submission lists, and the admin (Morgan) for the staff
 * console. Password: SEED_USER_PASSWORD (default BountyFlow!2026). A view that is empty for its account renders its
 * empty state, so it has nothing to capture and keeps the generic skeleton until data exists.
 *
 * Each run merges into the existing bones, so re-running after a layout change updates just what changed
 * (pass --force to recapture everything). The app loads each view's bones on demand (components/layout/Bones.tsx),
 * so the registry.ts the CLI also writes is removed: importing it would put every skeleton in the first-load bundle.
 */
import { spawnSync } from 'node:child_process'
import { rmSync } from 'node:fs'

const APP = (process.env.BONES_APP_URL ?? 'http://localhost:5173').replace(/\/$/, '')
const PASSWORD = process.env.SEED_USER_PASSWORD ?? process.env.E2E_SEED_PASSWORD ?? 'BountyFlow!2026'
const FORCE = process.argv.includes('--force')

const REQUESTER = 'ada.okafor@bountyflow.test'
const CONTRIBUTOR = 'kai.tanaka@bountyflow.test'
const ADMIN = 'morgan.reyes@bountyflow.test'

async function api(path, cookie) {
  const res = await fetch(`${APP}/api/v1${path}`, { headers: cookie ? { cookie } : {} })
  if (!res.ok) throw new Error(`GET ${path} failed: HTTP ${res.status}`)
  return res.json()
}

/** Signs in through the API and returns the access cookie ("bf_access=...") for the capture browser. */
async function signIn(email) {
  const res = await fetch(`${APP}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password: PASSWORD }),
  })
  if (!res.ok) {
    throw new Error(
      `Sign-in as ${email} failed (HTTP ${res.status}). Is the database seeded, and does SEED_USER_PASSWORD match?`,
    )
  }
  const access = res.headers.getSetCookie().find((c) => c.startsWith('bf_access='))
  if (!access) throw new Error(`Sign-in as ${email} returned no bf_access cookie`)
  return access.split(';')[0]
}

function capture(label, paths, cookie) {
  console.log(`\n── ${label}: ${paths.length} page(s)`)
  const args = ['exec', 'boneyard-js', 'build', ...paths.map((p) => APP + p), '--no-scan']
  if (FORCE) args.push('--force')
  if (cookie) args.push('--cookie', cookie)
  const run = spawnSync('pnpm', args, { stdio: 'inherit', shell: process.platform === 'win32' })
  if (run.status !== 0) process.exit(run.status ?? 1)
}

const featured = await api('/bounties/featured')
if (featured.length === 0)
  throw new Error('No open bounties to capture the bounty page from: seed the database first')
const bountyPath = `/bounties/${featured[0].slug || featured[0].id}`

capture('Public pages', ['/', '/bounties', bountyPath, '/u/kai-tanaka'])

const requester = await signIn(REQUESTER)
// The requester's bounty with the most applications, so its review pages have content to capture.
const mine = await api('/bounties/mine?page_size=50', requester)
const owned = [...mine.items].sort((a, b) => b.applications_count - a.applications_count)[0]
capture(
  'Workspace (requester)',
  [
    '/app',
    '/app/bounties',
    '/app/applications',
    '/app/submissions',
    '/app/payments',
    '/app/transactions',
    '/app/saved',
    '/app/notifications',
    '/app/analytics',
    '/app/profile',
    ...(owned
      ? [
          `/app/bounties/${owned.id}`,
          `/app/bounties/${owned.id}/applications`,
          `/app/bounties/${owned.id}/submissions`,
        ]
      : []),
  ],
  requester,
)

const contributor = await signIn(CONTRIBUTOR)
capture(
  'Workspace (contributor)',
  ['/app/applications', '/app/submissions', '/app/payments', '/app/saved'],
  contributor,
)

const admin = await signIn(ADMIN)
capture(
  'Staff console (admin)',
  [
    '/admin',
    '/admin/users',
    '/admin/bounties',
    '/admin/reports',
    '/admin/disputes',
    '/admin/transactions',
    '/admin/audit-logs',
  ],
  admin,
)

rmSync(new URL('../src/bones/registry.ts', import.meta.url), { force: true })
console.log('Skeletons updated in src/bones (loaded per view by components/layout/Bones.tsx).')
