import { handlers } from "@/auth"
import { withBackendSessionCookies } from "@/lib/auth/backend-session"

export const GET = withBackendSessionCookies(handlers.GET)
export const POST = withBackendSessionCookies(handlers.POST)
