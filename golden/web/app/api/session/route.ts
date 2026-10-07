import { NextResponse } from "next/server"

import { createDevIdentityToken } from "@/lib/api/client"
import { isLoopbackRequest, isSameOrigin, localDevSignInEnabled, SESSION_COOKIE, sessionCookieOptions } from "@/lib/auth/session"

const DEFAULT_MAX_AGE_SECONDS = 15 * 60
const MAX_FIELD_LENGTH = 200

function failure(message: string, status: number) {
  return NextResponse.json({ message }, { status })
}

/**
 * Local development sign-in: asks the backend's dev identity for a token and keeps it in an httpOnly cookie.
 * The route relays a caller into an identity that exists for this machine only, so it answers only in explicit local
 * mode, only to a request that names this app's own origin, and only to a caller on this machine.
 */
export async function POST(request: Request) {
  if (!localDevSignInEnabled()) return failure("Local development sign-in is off. It runs with `npm run dev`; a production build has none.", 404)
  if (!isSameOrigin(request)) return failure("Sign-in only accepts requests from this app.", 403)
  if (!isLoopbackRequest(request)) return failure("Local development sign-in only answers requests from this machine.", 403)

  let body: unknown
  try {
    body = await request.json()
  } catch {
    return failure("Send a JSON body.", 400)
  }
  const fields = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {}
  const email = typeof fields.email === "string" ? fields.email.trim() : ""
  const displayName = typeof fields.displayName === "string" ? fields.displayName.trim() : ""
  const invalidEmail = fields.email !== undefined && fields.email !== "" && (typeof fields.email !== "string" || !email.includes("@"))
  if (invalidEmail || email.length > MAX_FIELD_LENGTH || displayName.length > MAX_FIELD_LENGTH) {
    return failure("Enter a valid email address or none, and a display name of at most 200 characters.", 400)
  }

  let result
  try {
    result = await createDevIdentityToken({ ...(email ? { email } : {}), ...(displayName ? { displayName } : {}) })
  } catch {
    return failure("The backend is not reachable. Start it and check API_BASE_URL.", 502)
  }
  if (result.status === 404) {
    return failure("The backend offers no local development sign-in. Start it with the `local` profile.", 503)
  }
  if (!result.accessToken) {
    return failure(`The backend did not issue a token (status ${result.status}).`, 502)
  }

  const response = NextResponse.json({ ok: true })
  response.cookies.set(SESSION_COOKIE, result.accessToken, sessionCookieOptions(request, result.expiresIn ?? DEFAULT_MAX_AGE_SECONDS))
  return response
}

/** Sign-out: removes the session cookie. */
export async function DELETE(request: Request) {
  if (!isSameOrigin(request)) return failure("Sign-out only accepts requests from this app.", 403)
  const response = NextResponse.json({ ok: true })
  response.cookies.set(SESSION_COOKIE, "", sessionCookieOptions(request, 0))
  return response
}
