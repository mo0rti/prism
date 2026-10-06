"use client"

import { useRouter } from "next/navigation"

export function SignOutButton() {
  const router = useRouter()

  async function signOut() {
    await fetch("/api/session", { method: "DELETE" })
    router.push("/sign-in")
    router.refresh()
  }

  return (
    <button type="button" onClick={signOut}>
      Sign out
    </button>
  )
}
