import { signOut } from "next-auth/react"

// Revokes the backend refresh session first, then clears the Auth.js session.
// Returns false without signing out when the backend could not be reached, so
// the caller can tell the user to retry instead of leaving a live refresh token.
export async function signOutEverywhere(callbackUrl: string): Promise<boolean> {
  try {
    const response = await fetch("/api/session/logout", {
      method: "POST",
      headers: { Accept: "application/json" },
      cache: "no-store",
    })
    if (!response.ok) return false
  } catch {
    return false
  }
  await signOut({ callbackUrl })
  return true
}
