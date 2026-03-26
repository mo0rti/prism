import { NextIntlClientProvider } from "next-intl"
import { notFound } from "next/navigation"
import { auth } from "@/auth"
import { SiteHeader } from "@/components/layout/site-header"
import { AppSessionProvider } from "@/components/providers/session-provider"
import { ThemeProvider } from "@/components/providers/theme-provider"
import { getDirection, isValidLocale } from "@/lib/i18n/config"
import { routing } from "@/lib/i18n/routing"

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: { locale: string }
}) {
  if (!isValidLocale(params.locale)) {
    notFound()
  }

  const messages = (await import(`../../locales/${params.locale}/common.json`)).default
  const session = await auth()

  return (
    <div dir={getDirection(params.locale)}>
      <ThemeProvider>
        <AppSessionProvider session={session}>
          <NextIntlClientProvider locale={params.locale} messages={{ common: messages }}>
            <div className="min-h-screen">
              <SiteHeader locale={params.locale} />
              <main>{children}</main>
            </div>
          </NextIntlClientProvider>
        </AppSessionProvider>
      </ThemeProvider>
    </div>
  )
}
