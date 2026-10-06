"use client"

import { useRouter } from "next/navigation"
import { useState, type FormEvent } from "react"

export function SignInForm() {
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setPending(true)
    setError(null)
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.get("email"), displayName: form.get("displayName") }),
      })
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { message?: string } | null
        setError(payload?.message ?? `Sign-in failed (status ${response.status}).`)
        return
      }
      router.push("/")
      router.refresh()
    } catch {
      setError("Sign-in failed. Check that this app is running.")
    } finally {
      setPending(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="sign-in-form">
      <label>
        Email (optional)
        <input name="email" type="email" autoComplete="email" defaultValue="dev@example.com" />
      </label>
      <label>
        Display name (optional)
        <input name="displayName" type="text" autoComplete="name" maxLength={200} />
      </label>
      {error ? <p role="alert">{error}</p> : null}
      <button type="submit" disabled={pending}>
        {pending ? "Signing in..." : "Sign in"}
      </button>
    </form>
  )
}
