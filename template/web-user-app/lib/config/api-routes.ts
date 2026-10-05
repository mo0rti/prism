export const API_PREFIX = "/api/v1/"

export const PATH_MAPPINGS: Record<string, string> = {
  "/api/v1/health": "/actuator/health",
}

export function getBackendPath(frontendPath: string): string {
  return PATH_MAPPINGS[frontendPath] ?? frontendPath
}

const MAX_DECODE_ROUNDS = 4

function hasForbiddenCharacter(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i)
    if (code <= 0x1f || code === 0x7f) return true
  }
  return /[\\/;]/.test(value)
}

// A segment is safe only if no amount of percent-decoding turns it into a
// traversal, a separator or an absolute URL. Next.js already decodes `params`
// once, so encoded and double-encoded forms both reach this check.
function isSafeSegment(segment: unknown): segment is string {
  if (typeof segment !== "string" || segment === "") return false
  let value = segment
  for (let round = 0; round <= MAX_DECODE_ROUNDS; round++) {
    if (value === "." || value === ".." || hasForbiddenCharacter(value) || /^[a-z][a-z0-9+.-]*:/i.test(value)) {
      return false
    }
    let decoded: string
    try {
      decoded = decodeURIComponent(value)
    } catch {
      return false
    }
    if (decoded === value) return true
    value = decoded
  }
  return false
}

// Maps the proxy's catch-all segments to a backend path. Returns null for
// anything that is not a plain path under /api/v1/, so the bearer token is only
// ever sent to API routes. The one mapped route (health) is an explicit allowlist
// entry in PATH_MAPPINGS.
export function resolveProxyPath(segments: unknown): string | null {
  if (!Array.isArray(segments) || segments.length === 0 || !segments.every(isSafeSegment)) return null
  const frontendPath = `${API_PREFIX}${segments.map(encodeURIComponent).join("/")}`
  const backendPath = getBackendPath(frontendPath)
  if (backendPath === frontendPath) return frontendPath.startsWith(API_PREFIX) ? frontendPath : null
  return Object.values(PATH_MAPPINGS).includes(backendPath) ? backendPath : null
}
