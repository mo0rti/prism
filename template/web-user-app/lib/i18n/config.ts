export const locales = ["en", "nl"] as const
export type Locale = (typeof locales)[number]

export const defaultLocale: Locale = "en"

export function isValidLocale(locale: string): locale is Locale {
  return locales.includes(locale as Locale)
}

export function getDirection(_locale: string): "ltr" | "rtl" {
  return "ltr"
}
