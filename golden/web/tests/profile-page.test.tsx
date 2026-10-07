import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ProfilePage from "@/app/page"
import { getCurrentUser } from "@/lib/api/client"
import { readSessionToken } from "@/lib/auth/session"

vi.mock("@/lib/api/client", () => ({ getCurrentUser: vi.fn() }))
vi.mock("@/lib/auth/session", () => ({ readSessionToken: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  redirect: (path: string) => {
    throw new Error(`REDIRECT ${path}`)
  },
}))

const user = { id: "5b0e1c52-6d1d-4e3e-9a55-4c8f0d6f1a10", email: "ada@example.com", displayName: "Ada Lovelace", createdAt: "2026-10-06T10:00:00Z" }

describe("profile page (GET /api/me)", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockReset()
    vi.mocked(readSessionToken).mockReset()
  })

  it("shows the profile the client returns for the session token", async () => {
    vi.mocked(readSessionToken).mockResolvedValue("token-123")
    vi.mocked(getCurrentUser).mockResolvedValue({ status: 200, user })

    render(await ProfilePage())

    expect(getCurrentUser).toHaveBeenCalledWith("token-123")
    expect(screen.getByRole("heading", { name: "Your profile" })).toBeInTheDocument()
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument()
    expect(screen.getByText("ada@example.com")).toBeInTheDocument()
    expect(screen.getByText(user.id)).toBeInTheDocument()
    expect(screen.getByText(user.createdAt)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument()
  })

  it("shows a profile that has no email", async () => {
    vi.mocked(readSessionToken).mockResolvedValue("token-123")
    vi.mocked(getCurrentUser).mockResolvedValue({ status: 200, user: { id: user.id, displayName: "Dev", createdAt: user.createdAt } })

    render(await ProfilePage())

    expect(screen.getByText("Dev")).toBeInTheDocument()
    expect(screen.queryByText("Email")).not.toBeInTheDocument()
  })

  it("sends a visitor without a session to the sign-in", async () => {
    vi.mocked(readSessionToken).mockResolvedValue(undefined)

    await expect(ProfilePage()).rejects.toThrow("REDIRECT /sign-in")
    expect(getCurrentUser).not.toHaveBeenCalled()
  })

  it("sends the visitor to the sign-in when the backend rejects the token", async () => {
    vi.mocked(readSessionToken).mockResolvedValue("expired-token")
    vi.mocked(getCurrentUser).mockResolvedValue({ status: 401 })

    await expect(ProfilePage()).rejects.toThrow("REDIRECT /sign-in")
  })

  it("reports a failed read and an unreachable backend", async () => {
    vi.mocked(readSessionToken).mockResolvedValue("token-123")
    vi.mocked(getCurrentUser).mockResolvedValueOnce({ status: 500 })
    render(await ProfilePage())
    expect(screen.getByRole("alert")).toHaveTextContent("status 500")

    vi.mocked(getCurrentUser).mockRejectedValueOnce(new TypeError("fetch failed"))
    render(await ProfilePage())
    expect(screen.getAllByRole("alert").at(-1)).toHaveTextContent("not reachable")
  })
})
