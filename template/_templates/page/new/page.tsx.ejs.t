---
to: <%= target %>/src/app/<%= route %>/page.tsx
---
<% if (protected) { %>"use client"

import { useAuth } from "@/lib/auth/AuthContext"
import { useRouter } from "next/navigation"
import { useEffect } from "react"
<% } %>
export default function <%= h.changeCase.pascal(title.replace(/\s+/g, '')) %>Page() {
<% if (protected) { %>
  const { user, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading && !user) {
      router.push("/login")
    }
  }, [user, isLoading, router])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
      </div>
    )
  }

  if (!user) return null

<% } %>
  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-6"><%= title %></h1>

      {/* TODO: Page content */}
      <p className="text-gray-500">TODO: Implement <%= title %> page</p>
    </div>
  )
}
