import type { UserProfile } from "@/lib/api/client"

export function ProfileCard({ user }: { user: UserProfile }) {
  return (
    <dl className="profile-card">
      <dt>Name</dt>
      <dd>{user.displayName}</dd>
      {user.email ? (
        <>
          <dt>Email</dt>
          <dd>{user.email}</dd>
        </>
      ) : null}
      <dt>User ID</dt>
      <dd>{user.id}</dd>
      <dt>Created</dt>
      <dd>{user.createdAt}</dd>
    </dl>
  )
}
