import { createNavigation } from "next-intl/navigation"
import { defineRouting } from "next-intl/routing"
import { defaultLocale, locales } from "./config"

export const routing = defineRouting({
  locales: locales as unknown as [string, ...string[]],
  defaultLocale,
  pathnames: {
    "/": "/",
    "/login": "/login",
    "/dashboard": "/dashboard",
    "/dashboard/home": "/dashboard/home",
    "/dashboard/examples": "/dashboard/examples",
    "/dashboard/profile": "/dashboard/profile",
  },
})

export const { Link, redirect, usePathname, useRouter } = createNavigation(routing)
