"use client"

import { Layers3, Route, Shield } from "lucide-react"
import { useTranslations } from "next-intl"
import { useSession } from "next-auth/react"

export default function DashboardHomePage() {
  const session = useSession()
  const t = useTranslations("common.dashboard")

  const cards = [
    {
      title: t("examplesTitle"),
      body: t("examplesBody"),
      icon: Layers3,
    },
    {
      title: "Route handlers",
      body: "Use `/api/v1/*` to proxy backend requests without exposing cross-origin complexity to the UI layer.",
      icon: Route,
    },
    {
      title: t("profileTitle"),
      body: t("profileBody"),
      icon: Shield,
    },
  ]

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <p className="text-sm uppercase tracking-[0.2em] text-emerald-600">Dashboard</p>
        <h1 className="text-3xl font-semibold text-slate-900">{t("title")}</h1>
        <p className="max-w-3xl text-slate-600">
          {session.data?.user?.name ? `Signed in as ${session.data.user.name}. ` : ""}
          {t("description")}
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {cards.map((card) => (
          <div key={card.title} className="rounded-[1.5rem] border border-emerald-100 bg-white p-6 shadow-sm">
            <card.icon className="mb-4 h-6 w-6 text-emerald-600" />
            <h2 className="text-lg font-semibold text-slate-900">{card.title}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">{card.body}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
