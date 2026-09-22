import { DefaultSession } from "next-auth"
import { JWT } from "next-auth/jwt"

declare module "next-auth" {
  interface Session {
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
    role?: string
    accessToken?: string
    refreshToken?: string
    accessTokenExpires?: number
  }
}
