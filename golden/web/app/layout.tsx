import type { Metadata } from "next"
import type { ReactNode } from "react"

import { APP_AUDIENCE, APP_NAME } from "@/lib/app-info"

import "./globals.css"

export const metadata: Metadata = {
  title: APP_NAME,
  description: APP_AUDIENCE ? `${APP_NAME} for ${APP_AUDIENCE}` : APP_NAME,
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="app-header">
          <span className="app-name">{APP_NAME}</span>
          {APP_AUDIENCE ? <span className="app-audience">{APP_AUDIENCE}</span> : null}
        </header>
        <main>{children}</main>
      </body>
    </html>
  )
}
