import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import SignInPage from "@/app/sign-in/page"

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }))
vi.mock("next/navigation", () => ({ useRouter: () => router }))

describe("sign-in page", () => {
  beforeEach(() => {
    router.push.mockClear()
    router.refresh.mockClear()
  })

  it("is labelled Local development sign-in and says it is not complete authentication", () => {
    render(<SignInPage />)

    expect(screen.getByRole("heading", { name: "Local development sign-in" })).toBeInTheDocument()
    expect(screen.getByText(/not complete authentication/)).toBeInTheDocument()
  })

  it("posts the form to the session route and opens the profile", async () => {
    const send = vi.fn().mockResolvedValue(Response.json({ ok: true }))
    vi.stubGlobal("fetch", send)
    render(<SignInPage />)

    fireEvent.change(screen.getByLabelText(/^Email/), { target: { value: "ada@example.com" } })
    fireEvent.change(screen.getByLabelText(/Display name/), { target: { value: "Ada" } })
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }))

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"))
    expect(send).toHaveBeenCalledTimes(1)
    const [url, init] = send.mock.calls[0]
    expect(url).toBe("/api/session")
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body)).toEqual({ email: "ada@example.com", displayName: "Ada" })
    expect(router.refresh).toHaveBeenCalled()
  })

  it("shows the reason a sign-in failed and stays on the page", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ message: "The backend is not reachable." }, { status: 502 })))
    render(<SignInPage />)

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("The backend is not reachable.")
    expect(router.push).not.toHaveBeenCalled()
  })
})
