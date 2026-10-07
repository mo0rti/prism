// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { DELETE, POST } from "@/app/api/session/route"
import { SESSION_COOKIE } from "@/lib/auth/session"

const BACKEND = "http://backend.test"

const ORIGIN = "http://localhost:3000"

/** A sign-in request as the app's own page sends it: with the app's `Origin`, to a loopback host. */
function signInRequest(body: unknown, headers: Record<string, string> = {}, url = `${ORIGIN}/api/session`) {
  const origin = new URL(url).origin
  return new Request(url, {
    method: "POST",
    headers: { "content-type": "application/json", origin, ...headers },
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

// The route answers only in explicit local mode, which `.env.development` sets for `next dev`.
beforeEach(() => {
  vi.stubEnv("LOCAL_DEV_SIGNIN", "1")
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

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

    const direct = await POST(signInRequest({ email: "dev@example.com" }, {}, "https://localhost:3000/api/session"))
    const proxied = await POST(signInRequest({ email: "dev@example.com" }, { "x-forwarded-proto": "https", origin: "https://localhost:3000" }))

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

  it("is off outside explicit local mode and never calls the backend", async () => {
    const backend = stubBackend(issuedToken)
    vi.stubEnv("LOCAL_DEV_SIGNIN", "")

    const response = await POST(signInRequest({ email: "dev@example.com" }))

    expect(response.status).toBe(404)
    expect(response.headers.get("set-cookie")).toBeNull()
    expect(backend).not.toHaveBeenCalled()
  })

  it("refuses a request without an Origin header", async () => {
    const backend = stubBackend(issuedToken)
    const request = new Request(`${ORIGIN}/api/session`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: "dev@example.com" }),
    })

    const response = await POST(request)

    expect(response.status).toBe(403)
    expect(response.headers.get("set-cookie")).toBeNull()
    expect(backend).not.toHaveBeenCalled()
  })

  it("refuses a request whose peer is not on this machine, with or without a matching Origin", async () => {
    const backend = stubBackend(issuedToken)
    const remote = [
      // The host the caller used.
      signInRequest({ email: "x@example.com" }, {}, "http://192.168.1.20:3000/api/session"),
      signInRequest({ email: "x@example.com" }, {}, "http://app.example.com/api/session"),
      // A dev server bound to every interface: `request.url` carries the bound address, so it is refused whole.
      signInRequest({ email: "x@example.com" }, {}, "http://0.0.0.0:3000/api/session"),
      signInRequest({ email: "x@example.com" }, { host: "localhost:3000", origin: "http://localhost:3000" }, "http://0.0.0.0:3000/api/session"),
      // A tunnel or a proxy on this machine that forwards a remote caller.
      signInRequest({ email: "x@example.com" }, { "x-forwarded-for": "203.0.113.9" }),
      signInRequest({ email: "x@example.com" }, { "x-forwarded-for": "127.0.0.1, 203.0.113.9" }),
      signInRequest({ email: "x@example.com" }, { "x-forwarded-host": "app.example.com" }),
      signInRequest({ email: "x@example.com" }, { forwarded: "for=203.0.113.9" }),
    ]
    for (const request of remote) {
      const response = await POST(request)
      expect(response.status).toBe(403)
      expect(response.headers.get("set-cookie")).toBeNull()
    }
    expect(backend).not.toHaveBeenCalled()
  })

  it("answers a loopback caller by any of its names", async () => {
    stubBackend(issuedToken)
    for (const url of ["http://localhost:3000/api/session", "http://127.0.0.1:3000/api/session", "http://[::1]:3000/api/session"]) {
      const response = await POST(signInRequest({ email: "dev@example.com" }, { "x-forwarded-for": "127.0.0.1" }, url))
      expect(response.status).toBe(200)
    }
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
    const response = await DELETE(new Request(`${ORIGIN}/api/session`, { method: "DELETE", headers: { origin: ORIGIN } }))

    expect(response.status).toBe(200)
    const cookie = response.headers.get("set-cookie") ?? ""
    expect(cookie).toContain(`${SESSION_COOKIE}=;`)
    expect(cookie).toMatch(/Max-Age=0/i)
    expect(cookie).toMatch(/HttpOnly/i)
  })

  it("refuses a request without an Origin header", async () => {
    const response = await DELETE(new Request(`${ORIGIN}/api/session`, { method: "DELETE" }))

    expect(response.status).toBe(403)
  })

  it("refuses a request from another origin", async () => {
    const response = await DELETE(
      new Request("http://localhost:3000/api/session", { method: "DELETE", headers: { origin: "https://elsewhere.test" } }),
    )

    expect(response.status).toBe(403)
  })
})
