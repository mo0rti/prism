import { NextRequest, NextResponse } from "next/server"
import { backendSession, endSession } from "@/lib/auth/backend-session"

// Revokes the backend refresh session before the web session is cleared. Cookies
// are only cleared once the backend has answered, so a failed revocation stays
// retryable instead of leaving a live refresh token behind.
export async function POST(request: NextRequest) {
  let persist = async (response: NextResponse) => response
  try {
    const apiBaseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL
    if (!apiBaseUrl) {
      return NextResponse.json({ error: "API_BASE_URL is not configured." }, { status: 500 })
    }

    const session = await backendSession(request)
    persist = session.persist
    if (session.token?.accessToken) {
      const response = await fetch(`${apiBaseUrl}/api/v1/auth/logout`, {
        method: "POST",
        headers: { accept: "application/json", authorization: `Bearer ${session.token.accessToken}` },
        cache: "no-store",
        redirect: "manual",
        signal: AbortSignal.timeout(5000),
      })
      // 401 and 403 mean the backend already rejects these credentials.
      if (!response.ok && response.status !== 401 && response.status !== 403) {
        return persist(NextResponse.json({ error: "Sign out could not be completed" }, { status: 502 }))
      }
    }
    return endSession(request, new NextResponse(null, { status: 204 }))
  } catch {
    return persist(NextResponse.json({ error: "Sign out could not be completed" }, { status: 502 }))
  }
}
