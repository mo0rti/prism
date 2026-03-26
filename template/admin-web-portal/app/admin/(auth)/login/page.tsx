"use client"

import { FormEvent, useState } from "react"
import { signIn } from "next-auth/react"

export default function AdminLoginPage() {
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError(null)

    const formData = new FormData(event.currentTarget)
    const result = await signIn("credentials", {
      email: formData.get("email"),
      password: formData.get("password"),
      redirect: false,
      callbackUrl: "/admin",
    })

    if (result?.error) {
      setError("Admin credentials were rejected.")
      setLoading(false)
      return
    }

    window.location.assign("/admin")
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl items-center px-6 py-12">
      <div className="grid w-full gap-8 rounded-[2rem] border border-slate-200 bg-white/95 p-8 shadow-xl lg:grid-cols-[0.8fr_1.2fr]">
        <div className="space-y-4 rounded-[1.5rem] bg-slate-950 p-8 text-white">
          <p className="text-sm uppercase tracking-[0.2em] text-teal-300">Admin Web Portal</p>
          <h1 className="text-3xl font-semibold">Operations sign-in</h1>
          <p className="text-sm leading-7 text-slate-300">
            This scaffold mirrors the Ingredish admin direction: a dedicated `/admin` workspace with credentials-based access and operational screens.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-5 rounded-[1.5rem] border border-slate-200 p-6">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              className="w-full rounded-2xl border border-slate-200 px-4 py-3 outline-none transition focus:border-teal-400"
              placeholder="admin@example.com"
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              className="w-full rounded-2xl border border-slate-200 px-4 py-3 outline-none transition focus:border-teal-400"
              placeholder="••••••••"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="inline-flex w-full items-center justify-center rounded-2xl bg-teal-600 px-4 py-3 font-medium text-white transition hover:bg-teal-500 disabled:cursor-wait disabled:opacity-60"
          >
            {loading ? "Signing in..." : "Open admin web portal"}
          </button>
          {error ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          ) : null}
        </form>
      </div>
    </div>
  )
}
