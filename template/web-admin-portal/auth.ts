import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"
import { backendClaims, sessionCookie } from "@/lib/auth/backend-session"

export const { auth, handlers, signIn, signOut } = NextAuth({
  trustHost: true,
  cookies: { sessionToken: sessionCookie },
  providers: [
    Credentials({
      name: "Admin credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          return null
        }

        const apiBaseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL
        if (!apiBaseUrl) {
          return null
        }

        try {
          const response = await fetch(`${apiBaseUrl}/api/v1/auth/admin/login`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "application/json",
            },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
            }),
          })

          if (!response.ok) {
            return null
          }

          const payload = await response.json()
          const claims = backendClaims(payload)
          if (claims.role !== "ADMIN") return null

          return {
            ...claims,
            id: claims.userId,
          }
        } catch {
          return null
        }
      },
    }),
  ],
  pages: {
    signIn: "/admin/login",
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.userId = user.id
        token.role = (user as { role?: string }).role
        token.accessToken = (user as { accessToken?: string }).accessToken
        token.refreshToken = (user as { refreshToken?: string }).refreshToken
        token.accessTokenExpires = (user as { accessTokenExpires?: number }).accessTokenExpires
      }

      return token
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.id = token.userId as string
        session.user.role = token.role as string | undefined
      }

      return session
    },
  },
  session: {
    strategy: "jwt",
  },
})
