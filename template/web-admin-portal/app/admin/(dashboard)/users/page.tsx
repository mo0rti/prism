const sampleRows = [
  { email: "owner@example.com", status: "active", role: "ADMIN" },
  { email: "moderator@example.com", status: "invited", role: "MODERATOR" },
  { email: "support@example.com", status: "active", role: "SUPPORT" },
]

export default function AdminUsersPage() {
  return (
    <section className="space-y-5 rounded-[1.5rem] border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <h1 className="text-2xl font-semibold text-slate-950">Operators</h1>
        <p className="mt-2 text-sm text-slate-600">
          Replace this starter table with your own staff, admin, or moderation management flows.
        </p>
      </div>
      <div className="overflow-hidden rounded-2xl border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-3 font-medium">Email</th>
              <th className="px-4 py-3 font-medium">Role</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {sampleRows.map((row) => (
              <tr key={row.email}>
                <td className="px-4 py-3 text-slate-900">{row.email}</td>
                <td className="px-4 py-3 text-slate-600">{row.role}</td>
                <td className="px-4 py-3 text-slate-600">{row.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
