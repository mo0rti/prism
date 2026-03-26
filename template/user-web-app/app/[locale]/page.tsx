"use client"

import { ArrowRight, Globe2, LayoutDashboard, ShieldCheck } from "lucide-react"
import { useTranslations } from "next-intl"
import { Link } from "@/lib/i18n/routing"

export default function HomePage() {
  const t = useTranslations("common.home")

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-16 px-6 py-16">
      <section className="grid gap-12 rounded-[2rem] border border-emerald-100 bg-white/85 p-10 shadow-soft backdrop-blur lg:grid-cols-[1.3fr_0.7fr]">
        <div className="space-y-6">
          <span className="inline-flex rounded-full bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">
            {t("eyebrow")}
          </span>
          <div className="space-y-4">
            <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
              {t("title")}
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-slate-600">{t("description")}</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/dashboard/home"
              className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-5 py-3 font-medium text-white transition hover:bg-emerald-500"
            >
              {t("primaryCta")}
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-full border border-emerald-200 px-5 py-3 font-medium text-emerald-700 transition hover:border-emerald-300 hover:bg-emerald-50"
            >
              {t("secondaryCta")}
            </Link>
          </div>
        </div>

        <div className="grid gap-4">
          <div className="rounded-3xl bg-slate-900 p-6 text-white">
            <Globe2 className="mb-4 h-8 w-8 text-emerald-300" />
            <h2 className="text-xl font-semibold">{t("marketingTitle")}</h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">{t("marketingBody")}</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-3xl border border-emerald-100 bg-emerald-50 p-5">
              <LayoutDashboard className="mb-3 h-6 w-6 text-emerald-700" />
              <p className="text-sm font-medium text-emerald-900">Public + dashboard route split</p>
            </div>
            <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
              <ShieldCheck className="mb-3 h-6 w-6 text-slate-700" />
              <p className="text-sm font-medium text-slate-900">NextAuth session shell</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
