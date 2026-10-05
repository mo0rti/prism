"use client"

import { Moon, Sun } from "lucide-react"
import { useSession } from "next-auth/react"
import { useTheme } from "next-themes"
import { useState } from "react"
import { signOutEverywhere } from "@/lib/auth/sign-out"
import { Link, usePathname } from "@/lib/i18n/routing"
import { cn } from "@/lib/utils"

const items = [
  { href: "/dashboard/home", label: "Home" },
  { href: "/dashboard/examples", label: "Examples" },
  { href: "/dashboard/profile", label: "Profile" },
] as const

export function DashboardShell({
  children,
  locale,
}: {
  children: React.ReactNode
  locale: string
}) {
  const pathname = usePathname()
  const { data: session } = useSession()
  const { resolvedTheme, setTheme } = useTheme()
  const [signOutFailed, setSignOutFailed] = useState(false)

  async function handleSignOut() {
    setSignOutFailed(false)
    setSignOutFailed(!(await signOutEverywhere(`/${locale}/login`)))
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-10">
      <div className="flex flex-col gap-4 rounded-[1.75rem] border border-slate-200 bg-white p-5 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm text-slate-500">Signed in</p>
          <p className="font-medium text-slate-900">{session?.user?.email}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded-full px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-emerald-50 hover:text-emerald-700",
                pathname === item.href && "bg-emerald-100 text-emerald-800",
              )}
            >
              {item.label}
            </Link>
          ))}
          <button
            type="button"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
            className="rounded-full border border-slate-200 p-2 text-slate-600 transition hover:bg-slate-50"
            aria-label="Toggle color theme"
          >
            {resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={handleSignOut}
            className="rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            Sign Out
          </button>
          {signOutFailed ? (
            <p role="alert" className="text-sm text-rose-600">
              Sign out could not be completed. Try again.
            </p>
          ) : null}
        </div>
      </div>
      {children}
    </div>
  )
}
