import net from 'node:net'

/**
 * Minimal RESP client used only by the E2E harness to reset the API's
 * per-IP rate-limit counters in the isolated E2E Redis database (every
 * browser request reaches the API from 127.0.0.1, so a full suite run would
 * otherwise trip the register/login limits). Never point this at a shared
 * Redis database.
 */
const REDIS_URL = process.env.E2E_REDIS_URL ?? 'redis://localhost:6379/5'

function encode(args: string[]): string {
  return `*${args.length}\r\n${args.map((a) => `$${Buffer.byteLength(a)}\r\n${a}\r\n`).join('')}`
}

function command(args: string[][]): Promise<string> {
  const url = new URL(REDIS_URL)
  const db = url.pathname.replace('/', '') || '0'
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: url.hostname, port: Number(url.port || 6379) })
    let buffer = ''
    const expected = args.length + 1 // SELECT + commands
    const timer = setTimeout(() => {
      socket.destroy()
      reject(new Error('Redis command timed out'))
    }, 5_000)
    socket.on('connect', () => {
      socket.write(encode(['SELECT', db]) + args.map(encode).join(''))
    })
    socket.on('data', (chunk) => {
      buffer += chunk.toString('utf8')
      // Each reply we issue is a single line (+OK / :N / -ERR).
      const lines = buffer.split('\r\n').filter(Boolean)
      if (lines.length >= expected) {
        clearTimeout(timer)
        socket.end()
        const err = lines.find((l) => l.startsWith('-'))
        if (err) reject(new Error(`Redis error: ${err}`))
        else resolve(lines.slice(1).join('\n'))
      }
    })
    socket.on('error', (e) => {
      clearTimeout(timer)
      reject(e)
    })
  })
}

const DELETE_BY_PATTERN = `local n = 0
for _, k in ipairs(redis.call('KEYS', ARGV[1])) do redis.call('DEL', k); n = n + 1 end
return n`

/** The Redis database the harness clears, for error messages. */
export const E2E_REDIS_URL = REDIS_URL

/**
 * Clears the API's fixed-window rate-limit counters (`bf:v1:rl:*`) and returns how many it removed, or null
 * when Redis could not be reached.
 */
export async function resetRateLimits(): Promise<number | null> {
  try {
    const reply = await command([['EVAL', DELETE_BY_PATTERN, '0', 'bf:v1:rl:*']])
    const cleared = Number(reply.trim().replace(/^:/, ''))
    return Number.isFinite(cleared) ? cleared : 0
  } catch (e) {
    // The suite still works without it; it only risks 429s on repeated runs.
    console.warn(`[e2e] could not reset rate limits: ${(e as Error).message}`)
    return null
  }
}
