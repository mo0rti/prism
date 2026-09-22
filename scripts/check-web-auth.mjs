// Run against an installed generated web slice: node scripts/check-web-auth.mjs <app>.
// Transpile the actual sources and use Auth.js encryption and Next request/cookie
// implementations. Only the provider/backend network and NextAuth setup are stubbed.
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"
import { pathToFileURL } from "node:url"

const app = path.resolve(process.argv[2])
const require = createRequire(path.join(app, "package.json"))
const ts = require("typescript")
const next = await import(pathToFileURL(require.resolve("next/server.js")))
const jwt = await import(pathToFileURL(require.resolve("next-auth/jwt")))
const { NextRequest, NextResponse } = next
process.env.AUTH_SECRET = "prism-test-secret-for-local-regression-only"
process.env.API_BASE_URL = "https://backend.example.test"
process.env.AUTH_URL = "https://web.example.test"
const replacements = new Map()
let moduleCounter = 0
function moduleUrl(relative, extra = new Map()) {
  let source = ts.transpileModule(fs.readFileSync(path.join(app, relative), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText.replace(/import ["']server-only["'];?/g, "")
  source = source.replace(/from (["'])([^"']+)\1/g, (_, quote, specifier) => {
    const mapped = extra.get(specifier) || replacements.get(specifier)
    return `from ${JSON.stringify(mapped || pathToFileURL(require.resolve(specifier === "next/server" ? "next/server.js" : specifier)).href)}`
  })
  return `data:text/javascript;base64,${Buffer.from(source + `\n// module ${moduleCounter++}`).toString("base64")}`
}
const helperUrl = moduleUrl("lib/auth/backend-session.ts")
replacements.set("@/lib/auth/backend-session", helperUrl)
const helper = await import(helperUrl)
replacements.set("@/lib/config/api-routes", moduleUrl("lib/config/api-routes.ts"))
const route = await import(moduleUrl("app/api/v1/[...path]/route.ts"))
const capture = "data:text/javascript,export default config => { globalThis.prismAuthConfig = config; return {}; }"
await import(moduleUrl("auth.ts", new Map([["next-auth", capture]])))
const config = globalThis.prismAuthConfig
delete globalThis.prismAuthConfig
const admin = app.endsWith("web-admin-portal")
const name = helper.backendCookie.name
const authName = helper.sessionCookie.name
assert.ok(name.startsWith("__Secure-"))
assert.equal(helper.sessionCookie.options.httpOnly, true)

const originalFetch = globalThis.fetch
const payload = (role = "ADMIN") => ({
  accessToken: "new-access", refreshToken: "new-refresh", expiresIn: 3600,
  user: { id: "account-1", email: "test@example.com", displayName: "Test", role },
})
const claims = {
  userId: "account-1", accessToken: "old-access", refreshToken: "old-refresh",
  role: "ADMIN", accessTokenExpires: Date.now() - 1,
}
async function request(token = claims) {
  const value = await jwt.encode({ token, secret: process.env.AUTH_SECRET, salt: name, maxAge: 3600 })
  // Exercise Auth.js's real chunk reassembly, including an obsolete trailing chunk.
  const cookies = value.length > 3936
    ? Array.from({ length: Math.ceil(value.length / 3936) }, (_, i) => `${name}.${i}=${value.slice(i * 3936, (i + 1) * 3936)}`)
    : [`${name}=${value}`]
  const identity = await jwt.encode({ token: { userId: token.userId, role: token.role }, secret: process.env.AUTH_SECRET, salt: authName, maxAge: 3600 })
  cookies.push(`${authName}=${identity}`)
  return new NextRequest("https://web.example.test/api/v1/users/me", { headers: { cookie: cookies.join("; ") } })
}
async function replay(response, original) {
  original ||= await request()
  const cookies = new Map(original.cookies.getAll().map(c => [c.name, c.value]))
  for (const c of response.cookies.getAll()) {
    if (!c.value) cookies.delete(c.name)
    else cookies.set(c.name, c.value)
  }
  return new NextRequest("https://web.example.test/api/v1/users/me", { headers: {
    cookie: [...cookies].map(([name, value]) => `${name}=${value}`).join("; "),
  } })
}

try {
  for (const expiresIn of [0, -1, Infinity, NaN]) {
    assert.throws(() => helper.backendClaims({ ...payload(), expiresIn }))
  }
  let calls = 0
  globalThis.fetch = async () => { calls++; return Response.json(payload()) }
  const fresh = await helper.backendSession(await request({ ...claims, accessTokenExpires: Date.now() + 3600000 }))
  assert.equal(fresh.token.accessToken, "old-access")
  assert.equal(calls, 0)

  const sessions = await Promise.all([helper.backendSession(await request()), helper.backendSession(await request())])
  assert.equal(calls, 2)
  for (const session of sessions) {
    assert.equal(session.token.accessToken, "new-access")
    const response = await session.persist(NextResponse.json({ ok: true }))
    assert.match(response.headers.get("set-cookie"), /HttpOnly/)
    assert.match(response.headers.get("set-cookie"), /Secure/)
    const restored = await helper.backendSession(await replay(response))
    assert.equal(restored.token.refreshToken, "new-refresh")
  }
  assert.equal(calls, 2, "persisted refreshed cookies must not refresh again")

  const largeRequest = await request({ ...claims, padding: "x".repeat(12000) })
  const largeSession = await helper.backendSession(largeRequest)
  const largeResponse = await largeSession.persist(NextResponse.json({ ok: true }))
  assert.ok(largeResponse.cookies.getAll().filter(c => c.value).length > 1)
  assert.equal((await helper.backendSession(await replay(largeResponse, largeRequest))).token.refreshToken, "new-refresh")

  // Reproduce the actual Auth.js session action's delayed Set-Cookie behavior.
  const { Auth } = await import(pathToFileURL(require.resolve("@auth/core")))
  const originalRequest = await request()
  const authResponse = await Auth(new Request("https://web.example.test/api/auth/session", { headers: originalRequest.headers }), { ...config, basePath: "/api/auth", secret: process.env.AUTH_SECRET })
  const sessionResponse = new NextResponse(await authResponse.text(), { status: authResponse.status, headers: authResponse.headers })
  assert.equal(sessionResponse.status, 200)
  assert.ok(sessionResponse.cookies.getAll().some(c => c.name === authName))
  assert.ok(sessionResponse.cookies.getAll().every(c => !c.name.startsWith(name)))
  const refreshed = await (await helper.backendSession(originalRequest)).persist(NextResponse.json({ ok: true }))
  const reordered = await replay(sessionResponse, await replay(refreshed, originalRequest))
  assert.equal((await helper.backendSession(reordered)).token.refreshToken, "new-refresh", "late Auth.js session response must not roll back backend refresh state")

  // Drive actual Auth.js CSRF and credentials callback requests through the
  // production cookie wrapper, instead of constructing the login JWT ourselves.
  const authConfig = { ...config, basePath: "/api/auth", secret: process.env.AUTH_SECRET }
  const csrfResult = await Auth(new Request("https://web.example.test/api/auth/csrf"), authConfig)
  const csrfResponse = new NextResponse(await csrfResult.text(), { status: csrfResult.status, headers: csrfResult.headers })
  const csrfToken = (await csrfResponse.json()).csrfToken
  assert.equal(typeof csrfToken, "string")
  const csrfCookies = csrfResponse.cookies.getAll().map(c => `${c.name}=${c.value}`).join("; ")
  globalThis.fetch = async url => {
    assert.ok(url.endsWith(admin ? "/auth/admin/login" : "/auth/login"))
    return Response.json(payload(admin ? "ADMIN" : "USER"))
  }
  const actualLogin = await helper.withBackendSessionCookies(req => Auth(req, authConfig))(new NextRequest("https://web.example.test/api/auth/callback/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", cookie: csrfCookies },
    body: new URLSearchParams({ csrfToken, email: "test@example.invalid", password: "local-regression-only", callbackUrl: "https://web.example.test/" }),
  }))
  assert.ok(actualLogin.cookies.getAll().some(c => c.name === name && c.value), "real credentials callback must issue the backend cookie")
  const actualCookies = await replay(actualLogin, new NextRequest("https://web.example.test/api/v1/users/me"))
  const actualIdentity = await jwt.getToken({ req: actualCookies, secret: process.env.AUTH_SECRET, cookieName: authName, salt: authName })
  assert.equal(actualIdentity.userId, "account-1")
  assert.equal(actualIdentity.refreshToken, undefined)
  assert.equal(actualIdentity.accessToken, undefined)
  assert.equal((await helper.backendSession(actualCookies)).token.refreshToken, "new-refresh")
  const actualSession = await Auth(new Request("https://web.example.test/api/auth/session", { headers: actualCookies.headers }), authConfig)
  const actualSessionText = await actualSession.text()
  assert.equal(JSON.parse(actualSessionText).user.id, "account-1")
  for (const secret of ["accessToken", "refreshToken", "new-access", "new-refresh"]) assert.ok(!actualSessionText.includes(secret))

  const loginToken = await jwt.encode({ token: claims, secret: process.env.AUTH_SECRET, salt: authName, maxAge: 3600 })
  const login = await helper.withBackendSessionCookies(async () => {
    const response = new NextResponse(null, { status: 302, headers: { location: "/" } })
    response.cookies.set(authName, loginToken, helper.sessionCookie.options)
    return response
  })(new NextRequest("https://web.example.test/api/auth/callback/credentials"))
  const loginCookies = await replay(login)
  const identity = await jwt.getToken({ req: loginCookies, secret: process.env.AUTH_SECRET, cookieName: authName, salt: authName })
  assert.equal(identity.userId, claims.userId)
  assert.equal(identity.accessToken, undefined)
  assert.equal(identity.refreshToken, undefined)
  const privateSession = await jwt.getToken({ req: loginCookies, secret: process.env.AUTH_SECRET, cookieName: name, salt: name })
  assert.equal(privateSession.refreshToken, "old-refresh")
  const signout = await helper.withBackendSessionCookies(async () => {
    const response = NextResponse.json({ url: "/" })
    response.cookies.set(authName, "", { ...helper.sessionCookie.options, maxAge: 0 })
    return response
  })(new NextRequest("https://web.example.test/api/auth/signout", { method: "POST", headers: loginCookies.headers }))
  const signedOut = signout.cookies.getAll().filter(c => c.name === name)
  assert.equal(signedOut.length, 1)
  assert.ok(signedOut.every(c => c.value === "" && c.maxAge === 0))
  globalThis.fetch = async () => Response.json({}, { status: 401 })
  const rejected = await helper.backendSession(largeRequest)
  assert.equal(rejected.token, null)
  const cleared = await rejected.persist(NextResponse.json({}, { status: 401 }))
  assert.ok(cleared.cookies.getAll().length > 1)
  assert.ok(cleared.cookies.getAll().every(c => c.value === "" && c.maxAge === 0))

  globalThis.fetch = async () => Response.json({}, { status: 503 })
  await assert.rejects(helper.backendSession(await request()), /unavailable/)
  const outage = await route.GET(await request(), { params: { path: ["users", "me"] } })
  assert.equal(outage.status, 500)
  assert.equal(outage.headers.get("set-cookie"), null, "outage must preserve the retryable session")
  assert.deepEqual(await outage.json(), { error: "Proxy Error" })
  globalThis.fetch = async () => { throw new Error("private host/address") }
  await assert.rejects(helper.backendSession(await request()), /private host/)

  const publicSession = await config.callbacks.session({
    session: { user: { name: "Test", email: "test@example.com" }, expires: "2099-01-01" }, token: claims,
  })
  assert.equal(publicSession.user.id, claims.userId)
  for (const secret of ["accessToken", "refreshToken", "old-access", "old-refresh"]) {
    assert.ok(!JSON.stringify(publicSession).includes(secret), `public session leaked ${secret}`)
  }
  calls = 0
  globalThis.fetch = async () => { calls++; throw new Error("must not rotate on SSR session reads") }
  await config.callbacks.jwt({ token: claims })
  assert.equal(calls, 0)

  if (admin) {
    for (const role of [undefined, "USER", "admin"]) {
      const denied = await route.GET(await request({ ...claims, role, accessTokenExpires: Date.now() + 3600000 }), { params: { path: ["users"] } })
      assert.equal(denied.status, 403)
    }
    const provider = config.providers[0]
    const authorize = provider.options?.authorize || provider.authorize
    for (const role of [undefined, "USER", "ADMIN"]) {
      globalThis.fetch = async url => {
        assert.ok(url.endsWith("/auth/admin/login"))
        return Response.json(payload(role === undefined ? "" : role))
      }
      const user = await authorize({ email: "test@example.com", password: "password" }, {})
      assert.equal(user?.role || null, role === "ADMIN" ? "ADMIN" : null)
    }
  } else {
    for (const provider of ["google", "apple", "facebook", "microsoft-entra-id"]) {
      globalThis.fetch = async (url, init) => {
        assert.ok(url.endsWith("/auth/oauth/token"))
        const body = JSON.parse(init.body)
        assert.equal(body.provider, provider === "microsoft-entra-id" ? "microsoft" : provider)
        assert.equal(body.idToken, "signed-provider-token")
        assert.equal(body.accessToken, provider === "facebook" ? "provider-access" : undefined)
        return Response.json(payload("USER"))
      }
      const result = await config.callbacks.jwt({ token: {}, user: { id: "untrusted-browser-id" }, account: { provider, id_token: "signed-provider-token", access_token: "provider-access" } })
      assert.equal(result.userId, "account-1")
      assert.equal(result.refreshToken, "new-refresh")
    }
    globalThis.fetch = async () => Response.json({}, { status: 401 })
    await assert.rejects(config.callbacks.jwt({ token: {}, account: { provider: "google", id_token: "forged" } }), /verification failed/)
  }
  console.log(`PASS: ${path.basename(app)} encrypted cookies, refresh persistence, concurrency, rejection, outages, public session and admission checks`)
} finally { globalThis.fetch = originalFetch }
