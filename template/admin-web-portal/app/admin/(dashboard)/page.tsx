export default function AdminDashboardPage() {
  const cards = [
    {
      title: "Operations snapshot",
      body: "Use this page for high-level metrics, queue health, and system activity.",
    },
    {
      title: "Moderation and content",
      body: "Extend this scaffold with tables, filters, and action dialogs for operational workflows.",
    },
    {
      title: "Support tooling",
      body: "Add user support, manual adjustments, refunds, or content review flows here.",
    },
  ]

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <p className="text-sm uppercase tracking-[0.2em] text-teal-600">Admin Web Portal</p>
        <h1 className="text-3xl font-semibold text-slate-950">Operations dashboard</h1>
        <p className="max-w-3xl text-slate-600">
          This shell is modeled on the Ingredish admin portal: a protected `/admin` space with quick access to management workflows.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {cards.map((card) => (
          <div key={card.title} className="rounded-[1.5rem] border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-950">{card.title}</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">{card.body}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
