---
to: <%= target === 'user-web-app' ? `user-web-app/app/[locale]/dashboard/${route}/page.tsx` : `admin-web-portal/app/admin/(dashboard)/${route}/page.tsx` %>
---
export default function <%= h.changeCase.pascal(title.replace(/\s+/g, '')) %>Page() {
  return (
    <section className="rounded-[1.5rem] border border-dashed border-slate-200 bg-white/80 p-8">
      <h1 className="mb-3 text-2xl font-bold"><%= title %></h1>

      {/* TODO: Page content */}
      <p className="text-sm text-gray-500">TODO: Implement <%= title %> page</p>
    </section>
  )
}
