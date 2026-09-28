/**
 * A short, readable name for a session's device, e.g. "Chrome on Windows", from its User-Agent header. Unknown
 * clients fall back to their product token (e.g. "curl"), then to "Unknown device".
 */
export function describeUserAgent(ua: string | null | undefined): string {
  if (!ua) return 'Unknown device'

  const os = /iPhone|iPad|iPod/.test(ua)
    ? /iPad/.test(ua)
      ? 'iPad'
      : 'iPhone'
    : /Android/.test(ua)
      ? 'Android'
      : /Windows/.test(ua)
        ? 'Windows'
        : /Mac OS X|Macintosh/.test(ua)
          ? 'macOS'
          : /CrOS/.test(ua)
            ? 'ChromeOS'
            : /Linux/.test(ua)
              ? 'Linux'
              : null

  // Order matters: Edge and Opera also say "Chrome", Chrome also says "Safari".
  const browser = /Edg\//.test(ua)
    ? 'Edge'
    : /OPR\/|Opera/.test(ua)
      ? 'Opera'
      : /Firefox\//.test(ua)
        ? 'Firefox'
        : /HeadlessChrome\//.test(ua)
          ? 'Headless Chrome'
          : /Chrome\/|CriOS\//.test(ua)
            ? 'Chrome'
            : /Safari\//.test(ua)
              ? 'Safari'
              : null

  if (browser) return os ? `${browser} on ${os}` : browser
  const product = ua.split(/[/\s]/)[0]
  return product || 'Unknown device'
}
