import net from 'node:net'

/**
 * Registers a gist for the API's recorded-GitHub transport, which the backend only enables in test mode
 * (`GITHUB_FIXTURE_TRANSPORT=true`, refused outside development/test). The API reads the gist body from Redis
 * (`tests/support/github_fixtures.py`), so the suite never depends on a real person's gist while still
 * exercising the real verification code against recorded GitHub responses.
 *
 * The recorded pull requests these tests use live in `backend/tests/fixtures/github`, captured from public
 * pull requests in `stellar/js-stellar-sdk`.
 */
const REDIS_URL = process.env.E2E_REDIS_URL ?? 'redis://localhost:6379/5'

/** The author of the recorded pull requests, and the account the tests link. */
export const GITHUB_LOGIN = 'Ryang-21'
export const GITHUB_USER_ID = 104600435

export const REPO_URL = 'https://github.com/stellar/js-stellar-sdk'
export const MERGED_PR_URL = `${REPO_URL}/pull/1744`
export const OPEN_PR_URL = `${REPO_URL}/pull/1747`
/** Opened by someone else (a fork), so it verifies as an author mismatch. */
export const FOREIGN_PR_URL = `${REPO_URL}/pull/1739`

function encode(args: string[]): string {
  return `*${args.length}\r\n${args.map((a) => `$${Buffer.byteLength(a)}\r\n${a}\r\n`).join('')}`
}

function send(args: string[][]): Promise<void> {
  const url = new URL(REDIS_URL)
  const db = url.pathname.replace('/', '') || '0'
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: url.hostname, port: Number(url.port || 6379) })
    let replies = 0
    const timer = setTimeout(() => {
      socket.destroy()
      reject(new Error('Redis command timed out'))
    }, 5_000)
    socket.on('connect', () => socket.write(encode(['SELECT', db]) + args.map(encode).join('')))
    socket.on('data', (chunk) => {
      replies += chunk.toString('utf8').split('\r\n').filter(Boolean).length
      if (replies >= args.length + 1) {
        clearTimeout(timer)
        socket.end()
        resolve()
      }
    })
    socket.on('error', (e) => {
      clearTimeout(timer)
      reject(e)
    })
  })
}

/** Publishes a gist the API's test transport will serve, owned by `login` and holding `content`. */
export async function registerFixtureGist(
  gistId: string,
  content: string,
  login = GITHUB_LOGIN,
  userId = GITHUB_USER_ID,
): Promise<void> {
  const value = JSON.stringify({ owner_login: login, owner_id: userId, content })
  await send([['SET', `bf:v1:github:fixture-gist:${gistId.toLowerCase()}`, value, 'EX', '3600']])
}

export const gistUrl = (gistId: string, login = GITHUB_LOGIN) =>
  `https://gist.github.com/${login}/${gistId}`
