import "server-only"
import { encode, getToken, JWT } from "next-auth/jwt"
import { NextRequest, NextResponse } from "next/server"

export const sessionCookie = {
  name: `${(process.env.AUTH_URL || process.env.NEXTAUTH_URL || (process.env.NODE_ENV === "production" ? "https:" : "http:")).startsWith("https:") ? "__Secure-" : ""}authjs.session-token`,
  options: {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    secure: (process.env.AUTH_URL || process.env.NEXTAUTH_URL || (process.env.NODE_ENV === "production" ? "https:" : "http:")).startsWith("https:"),
  },
}

// Auth.js rewrites its own cookie during session reads. Refresh credentials use
// a separate cookie so a delayed /api/auth/session response cannot roll them back.
export const backendCookie = { ...sessionCookie, name: `${sessionCookie.options.secure ? "__Secure-" : ""}prism.backend-session` }
const sessionMaxAge = 30 * 24 * 60 * 60

async function replaceCookie(response: NextResponse, old: { name: string }[], cookie: typeof sessionCookie, token: JWT | null, secret: string, maxAge = sessionMaxAge) {
  for (const item of old) {
    if (item.name === cookie.name || item.name.startsWith(`${cookie.name}.`)) {
      response.cookies.set(item.name, "", { ...cookie.options, maxAge: 0 })
    }
  }
  if (token) {
    const encoded = await encode({ token, secret, salt: cookie.name, maxAge })
    const size = 3936
    for (let offset = 0; offset < encoded.length; offset += size) {
      const name = encoded.length <= size ? cookie.name : `${cookie.name}.${offset / size}`
      response.cookies.set(name, encoded.slice(offset, offset + size), { ...cookie.options, maxAge })
    }
  }
}

// Run only around the Auth.js route handlers. A successful callback transfers
// credentials into the backend cookie and removes them from the Auth.js token.
export function withBackendSessionCookies(handler: (request: NextRequest) => Promise<Response>) {
  return async (request: NextRequest) => {
    const result = await handler(request)
    const response = new NextResponse(result.body, { status: result.status, statusText: result.statusText, headers: result.headers })
    const changed = response.cookies.getAll().filter(c => c.name === sessionCookie.name || c.name.startsWith(`${sessionCookie.name}.`))
    if (!changed.length) return response
    const secret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET
    if (!secret) throw new Error("AUTH_SECRET is not configured")
    if (request.nextUrl.pathname.startsWith("/api/auth/callback/")) {
      const cookieHeader = changed.filter(c => c.value).map(c => `${c.name}=${c.value}`).join("; ")
      const token = await getToken({ req: new NextRequest(request.url, { headers: { cookie: cookieHeader } }), secret, cookieName: sessionCookie.name, salt: sessionCookie.name })
      if (token?.userId && token.accessToken && token.refreshToken) {
        const { accessToken, refreshToken, accessTokenExpires, ...identity } = token
        await replaceCookie(response, request.cookies.getAll(), backendCookie, { userId: token.userId, role: token.role, accessToken, refreshToken, accessTokenExpires }, secret)
        await replaceCookie(response, [...request.cookies.getAll(), ...changed], sessionCookie, identity, secret)
      }
    } else if (request.nextUrl.pathname === "/api/auth/signout" && changed.every(c => !c.value)) {
      await replaceCookie(response, request.cookies.getAll(), backendCookie, null, secret)
    }
    return response
  }
}

export function backendClaims(payload: unknown) {
  const value = payload as { accessToken?: unknown; refreshToken?: unknown; expiresIn?: unknown; user?: { id?: unknown; email?: unknown; displayName?: unknown; role?: unknown } }
  if (!value || typeof value.accessToken !== "string" || !value.accessToken ||
      typeof value.refreshToken !== "string" || !value.refreshToken ||
      typeof value.expiresIn !== "number" || !Number.isFinite(value.expiresIn) || value.expiresIn <= 0 ||
      typeof value.user?.id !== "string" || !value.user.id) {
    throw new Error("Invalid backend authentication response")
  }
  return {
    userId: value.user.id,
    email: typeof value.user.email === "string" ? value.user.email : null,
    name: typeof value.user.displayName === "string" ? value.user.displayName : null,
    role: typeof value.user.role === "string" ? value.user.role : undefined,
    accessToken: value.accessToken,
    refreshToken: value.refreshToken,
    accessTokenExpires: Date.now() + value.expiresIn * 1000,
  }
}

// Only route handlers refresh: they can persist Set-Cookie. Server-component
// auth() reads must not consume a rotating token without saving its replacement.
export async function backendSession(request: NextRequest) {
  const secret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET
  if (!secret) throw new Error("AUTH_SECRET is not configured")
  let token = await getToken({ req: request, secret, cookieName: backendCookie.name, salt: backendCookie.name, secureCookie: backendCookie.options.secure })
  const identity = await getToken({ req: request, secret, cookieName: sessionCookie.name, salt: sessionCookie.name, secureCookie: sessionCookie.options.secure })
  if (!identity?.userId || identity.userId !== token?.userId) token = null
  let changed = false
  if (token && (!token.accessTokenExpires || Date.now() >= token.accessTokenExpires - 30_000)) {
    if (!token.refreshToken) {
      token = null
      changed = true
    } else {
      const base = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL
      if (!base) throw new Error("API_BASE_URL is not configured")
      const response = await fetch(`${base}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refreshToken: token.refreshToken }),
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      })
      // A temporary outage must not destroy the retryable encrypted session.
      if (response.status === 401 || response.status === 403) {
        token = null
      } else {
        if (!response.ok) throw new Error("Backend session refresh unavailable")
        const claims = backendClaims(await response.json())
        if (claims.userId !== token.userId) throw new Error("Backend session identity changed")
        token = { ...token, ...claims }
      }
      changed = true
    }
  }
  const current: JWT | null = token
  return {
    token: current,
    async persist(response: NextResponse) {
      if (!changed) return response
      await replaceCookie(response, request.cookies.getAll(), backendCookie, current, secret)
      return response
    },
  }
}
