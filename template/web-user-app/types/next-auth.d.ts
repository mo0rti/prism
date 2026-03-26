import { DefaultSession } from "next-auth"
import { JWT } from "next-auth/jwt"

declare module "next-auth" {
  interface Session {
    accessToken?: string
    refreshToken?: string
    user: DefaultSession["user"] & {
      id: string
      provider?: string
    }
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    userId?: string
    provider?: string
    accessToken?: string
    refreshToken?: string
  }
}
