import { redirect } from "next/navigation"

import { ProfileCard } from "@/components/profile-card"
import { SignOutButton } from "@/components/sign-out-button"
import { getCurrentUser } from "@/lib/api/client"
import { readSessionToken } from "@/lib/auth/session"

// The profile belongs to the signed-in user, so the page is rendered per request.
export const dynamic = "force-dynamic"

/** The authenticated read of the slice: `GET /api/me` through the generated API client. */
export default async function ProfilePage() {
  const token = await readSessionToken()
  if (!token) redirect("/sign-in")

  let result
  try {
    result = await getCurrentUser(token)
  } catch {
    return (
      <section>
        <h1>Your profile</h1>
        <p role="alert">The backend is not reachable. Start it and check API_BASE_URL.</p>
      </section>
    )
  }
  if (result.status === 401) redirect("/sign-in")
  if (!result.user) {
    return (
      <section>
        <h1>Your profile</h1>
        <p role="alert">The profile could not be loaded (status {result.status}).</p>
      </section>
    )
  }

  return (
    <section>
      <h1>Your profile</h1>
      <ProfileCard user={result.user} />
      <SignOutButton />
    </section>
  )
}
