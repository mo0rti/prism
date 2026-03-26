---
to: <%= target === 'web-user-app' ? `web-user-app/app/[locale]/dashboard/${route}/loading.tsx` : `web-admin-portal/app/admin/(dashboard)/${route}/loading.tsx` %>
---
export default function Loading() {
  return (
    <div className="px-4 py-8">
      <div className="animate-pulse">
        <div className="h-8 bg-gray-200 rounded w-1/4 mb-6" />
        <div className="space-y-4">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
          <div className="h-4 bg-gray-200 rounded w-1/2" />
          <div className="h-4 bg-gray-200 rounded w-2/3" />
        </div>
      </div>
    </div>
  )
}
