// @vitest-environment node
import { describe, expect, it, vi } from "vitest"

import { DELETE, POST } from "@/app/api/session/route"
import { SESSION_COOKIE } from "@/lib/auth/session"

const BACKEND = "http://backend.test"

function signInRequest(body: unknown, headers: Record<string, string> = {}, url = "http://localhost:3000/api/session") {
  return new Request(url, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  })
}

/** Stands in for the backend: the API client calls `fetch` with a `Request`. */
function stubBackend(handler: (request: Request) => Response | Promise<Response>) {
  vi.stubEnv("API_BASE_URL", BACKEND)
  const backend = vi.fn(handler)
  vi.stubGlobal("fetch", backend)
  return backend
}

const issuedToken = () => Response.json({ accessToken: "token-123", tokenType: "Bearer", expiresIn: 600 })

describe("POST /api/session (local development sign-in)", () => {
  it("asks the backend's dev identity for a token", async () => {
    const backend = stubBackend(issuedToken)

    await POST(signInRequest({ email: "dev@example.com", displayName: "Dev User" }))

    expect(backend).toHaveBeenCalledTimes(1)
    const request = backend.mock.calls[0][0]
    expect(request.method).toBe("POST")
    expect(request.url).toBe(`${BACKEND}/api/dev-identity/token`)
    expect(await request.json()).toEqual({ email: "dev@example.com", displayName: "Dev User" })
  })

  it("keeps the token in an httpOnly cookie and never returns it in the body", async () => {
    stubBackend(issuedToken)

    const response = await POST(signInRequest({ email: "dev@example.com" }))

    expect(response.status).toBe(200)
    const cookie = response.headers.get("set-cookie") ?? ""
    expect(cookie).toContain(`${SESSION_COOKIE}=token-123`)
    expect(cookie).toMatch(/HttpOnly/i)
    expect(cookie).toMatch(/SameSite=lax/i)
    expect(cookie).toMatch(/Path=\//i)
    expect(cookie).toMatch(/Max-Age=600/i)
    expect(cookie).not.toMatch(/Secure/i)
    expect(await response.text()).not.toContain("token-123")
  })

  it("marks the cookie Secure when the request came over HTTPS", async () => {
    stubBackend(issuedToken)

    const direct = await POST(signInRequest({ email: "dev@example.com" }, {}, "https://app.test/api/session"))
    const proxied = await POST(signInRequest({ email: "dev@example.com" }, { "x-forwarded-proto": "https" }))

    expect(direct.headers.get("set-cookie")).toMatch(/Secure/i)
    expect(proxied.headers.get("set-cookie")).toMatch(/Secure/i)
  })

  it("refuses a request from another origin without calling the backend", async () => {
    const backend = stubBackend(issuedToken)

    const response = await POST(signInRequest({ email: "dev@example.com" }, { origin: "https://elsewhere.test" }))

    expect(response.status).toBe(403)
    expect(response.headers.get("set-cookie")).toBeNull()
    expect(backend).not.toHaveBeenCalled()
  })

  it("refuses a body that is not JSON or has an invalid email", async () => {
    const backend = stubBackend(issuedToken)

    for (const body of ["not json", { email: "no-at-sign" }, { email: 5 }]) {
      const response = await POST(signInRequest(body))
      expect(response.status).toBe(400)
      expect(response.headers.get("set-cookie")).toBeNull()
    }
    expect(backend).not.toHaveBeenCalled()
  })

  it("says so when the backend has no local development sign-in", async () => {
    stubBackend(() => new Response(null, { status: 404 }))

    const response = await POST(signInRequest({ email: "dev@example.com" }))

    expect(response.status).toBe(503)
    expect((await response.json()).message).toContain("`local` profile")
    expect(response.headers.get("set-cookie")).toBeNull()
  })

  it("sets no cookie when the backend is unreachable or issues no token", async () => {
    stubBackend(() => {
      throw new TypeError("fetch failed")
    })
    const unreachable = await POST(signInRequest({ email: "dev@example.com" }))
    expect(unreachable.status).toBe(502)
    expect(unreachable.headers.get("set-cookie")).toBeNull()

    stubBackend(() => new Response(null, { status: 500 }))
    const failed = await POST(signInRequest({ email: "dev@example.com" }))
    expect(failed.status).toBe(502)
    expect(failed.headers.get("set-cookie")).toBeNull()
  })
})

describe("DELETE /api/session (sign-out)", () => {
  it("expires the session cookie", async () => {
    const response = await DELETE(new Request("http://localhost:3000/api/session", { method: "DELETE" }))

    expect(response.status).toBe(200)
    const cookie = response.headers.get("set-cookie") ?? ""
    expect(cookie).toContain(`${SESSION_COOKIE}=;`)
    expect(cookie).toMatch(/Max-Age=0/i)
    expect(cookie).toMatch(/HttpOnly/i)
  })

  it("refuses a request from another origin", async () => {
    const response = await DELETE(
      new Request("http://localhost:3000/api/session", { method: "DELETE", headers: { origin: "https://elsewhere.test" } }),
    )

    expect(response.status).toBe(403)
  })
})
