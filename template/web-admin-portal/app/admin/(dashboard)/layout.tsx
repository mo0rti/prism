import { redirect } from "next/navigation"
import { auth } from "@/auth"
import { AdminShell } from "@/components/layout/admin-shell"

export default async function AdminDashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const session = await auth()

  if (!session) {
    redirect("/admin/login")
  }

  return <AdminShell>{children}</AdminShell>
}
