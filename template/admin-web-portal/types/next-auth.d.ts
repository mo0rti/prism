import { DefaultSession } from "next-auth"

declare module "next-auth" {
  interface Session {
    accessToken?: string
    refreshToken?: string
    user: DefaultSession["user"] & {
      id: string
      role?: string
    }
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    userId?: string
    role?: string
    accessToken?: string
    refreshToken?: string
  }
}
