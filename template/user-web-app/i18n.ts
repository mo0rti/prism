import { getRequestConfig } from "next-intl/server"
import { routing } from "@/lib/i18n/routing"

export default getRequestConfig(async ({ locale }) => {
  const resolvedLocale =
    locale && routing.locales.includes(locale as (typeof routing.locales)[number])
      ? locale
      : routing.defaultLocale

  const messages = (await import(`./locales/${resolvedLocale}/common.json`)).default

  return {
    locale: resolvedLocale,
    messages: {
      common: messages,
    },
    timeZone: "UTC",
  }
})
