import { redirect } from "next/navigation"
import { auth } from "@/auth"
import { DashboardShell } from "@/components/layout/dashboard-shell"

export default async function DashboardLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: { locale: string }
}) {
  const session = await auth()

  if (!session) {
    redirect(`/${params.locale}/login`)
  }

  return <DashboardShell locale={params.locale}>{children}</DashboardShell>
}
