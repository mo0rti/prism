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
const apiRoutesUrl = moduleUrl("lib/config/api-routes.ts")
replacements.set("@/lib/config/api-routes", apiRoutesUrl)
const apiRoutes = await import(apiRoutesUrl)
const route = await import(moduleUrl("app/api/v1/[...path]/route.ts"))
const logoutRoute = await import(moduleUrl("app/api/session/logout/route.ts"))
const signOutStub = "data:text/javascript,export const signOut = async options => { (globalThis.prismSignOutCalls ||= []).push(options) }"
const signOutHelper = await import(moduleUrl("lib/auth/sign-out.ts", new Map([["next-auth/react", signOutStub]])))
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
  assert.ok(cleared.cookies.getAll().some(c => c.name === authName), "a rejected refresh must also clear the Auth.js identity cookie")
  const afterRejection = await replay(cleared, largeRequest)
  assert.equal(await jwt.getToken({ req: afterRejection, secret: process.env.AUTH_SECRET, cookieName: authName, salt: authName }), null, "web session must end when the backend rejects the refresh")
  assert.equal(await jwt.getToken({ req: afterRejection, secret: process.env.AUTH_SECRET, cookieName: name, salt: name }), null)

  // An identity cookie without backend credentials (for example an expired backend cookie) ends the web session.
  const identityOnly = await jwt.encode({ token: { userId: claims.userId, role: claims.role }, secret: process.env.AUTH_SECRET, salt: authName, maxAge: 3600 })
  const orphan = await route.GET(new NextRequest("https://web.example.test/api/v1/users/me", { headers: { cookie: `${authName}=${identityOnly}` } }), { params: { path: ["users", "me"] } })
  assert.ok(orphan.cookies.getAll().some(c => c.name === authName && c.value === "" && c.maxAge === 0), "identity without backend credentials must end the web session")

  // Sign-out revokes the backend refresh session before any cookie is cleared.
  const live = { ...claims, accessTokenExpires: Date.now() + 3600000 }
  const backend = process.env.API_BASE_URL
  let logoutCalls = []
  globalThis.fetch = async (url, init) => {
    logoutCalls.push({ url, method: init?.method, authorization: new Headers(init?.headers).get("authorization") })
    return new Response(null, { status: 204 })
  }
  const signedOut204 = await logoutRoute.POST(new NextRequest("https://web.example.test/api/session/logout", { method: "POST", headers: (await request(live)).headers }))
  assert.deepEqual(logoutCalls, [{ url: `${backend}/api/v1/auth/logout`, method: "POST", authorization: "Bearer old-access" }])
  assert.equal(signedOut204.status, 204)
  assert.ok(signedOut204.cookies.getAll().every(c => c.value === "" && c.maxAge === 0))
  for (const cookie of [name, authName]) assert.ok(signedOut204.cookies.getAll().some(c => c.name === cookie), `logout must clear ${cookie}`)
  // An expired access token is refreshed first, then the rotated token is revoked.
  logoutCalls = []
  globalThis.fetch = async (url, init) => {
    logoutCalls.push({ url, authorization: new Headers(init?.headers).get("authorization") })
    return url.endsWith("/auth/refresh") ? Response.json(payload()) : new Response(null, { status: 204 })
  }
  const refreshedLogout = await logoutRoute.POST(await request())
  assert.deepEqual(logoutCalls.map(c => c.url), [`${backend}/api/v1/auth/refresh`, `${backend}/api/v1/auth/logout`])
  assert.equal(logoutCalls[1].authorization, "Bearer new-access")
  assert.equal(refreshedLogout.status, 204)
  // A backend failure keeps the session so sign-out can be retried; nothing is cleared.
  for (const failure of [async () => new Response(null, { status: 503 }), async () => { throw new Error("private host/address") }]) {
    globalThis.fetch = failure
    const failed = await logoutRoute.POST(await request(live))
    assert.equal(failed.status, 502)
    assert.equal(failed.headers.get("set-cookie"), null, "a failed revocation must not clear the session")
    assert.deepEqual(await failed.json(), { error: "Sign out could not be completed" })
  }
  // A rotation that happened before a failed revocation is still persisted.
  globalThis.fetch = async url => url.endsWith("/auth/refresh") ? Response.json(payload()) : new Response(null, { status: 503 })
  const rotatedThenFailed = await logoutRoute.POST(await request())
  assert.equal(rotatedThenFailed.status, 502)
  assert.ok(rotatedThenFailed.cookies.getAll().some(c => c.name === name && c.value), "rotated refresh token must be saved")
  // Credentials the backend already rejects (401/403) leave nothing to revoke.
  globalThis.fetch = async () => new Response(null, { status: 401 })
  const alreadyRevoked = await logoutRoute.POST(await request(live))
  assert.equal(alreadyRevoked.status, 204)
  assert.ok(alreadyRevoked.cookies.getAll().every(c => c.value === "" && c.maxAge === 0))
  // Without a session there is nothing to revoke and no backend call.
  globalThis.fetch = async () => { throw new Error("must not call the backend without a session") }
  assert.equal((await logoutRoute.POST(new NextRequest("https://web.example.test/api/session/logout", { method: "POST" }))).status, 204)

  // The browser helper revokes first and signs out locally only afterwards.
  const helperEvents = []
  globalThis.prismSignOutCalls = []
  globalThis.fetch = async (url, init) => { helperEvents.push(`${init.method} ${url}`); return new Response(null, { status: 204 }) }
  assert.equal(await signOutHelper.signOutEverywhere("/login"), true)
  assert.deepEqual(helperEvents, ["POST /api/session/logout"])
  assert.deepEqual(globalThis.prismSignOutCalls, [{ callbackUrl: "/login" }])
  globalThis.prismSignOutCalls = []
  for (const failure of [async () => new Response(null, { status: 502 }), async () => { throw new Error("offline") }]) {
    globalThis.fetch = failure
    assert.equal(await signOutHelper.signOutEverywhere("/login"), false)
  }
  assert.deepEqual(globalThis.prismSignOutCalls, [], "a failed revocation must not clear the local session")
  delete globalThis.prismSignOutCalls
  // Every sign-out goes through the helper, never a bare next-auth signOut().
  const sources = []
  const walk = folder => fs.readdirSync(path.join(app, folder), { withFileTypes: true }).forEach(entry => {
    const relative = path.join(folder, entry.name)
    if (entry.isDirectory()) walk(relative)
    else if (/\.tsx?$/.test(entry.name)) sources.push(relative.replaceAll("\\", "/"))
  })
  for (const folder of ["app", "components", "lib"]) walk(folder)
  const read = file => fs.readFileSync(path.join(app, file), "utf8")
  assert.deepEqual(sources.filter(file => /\bsignOut\s*\(/.test(read(file))), ["lib/auth/sign-out.ts"], "components must call signOutEverywhere, not signOut")
  assert.ok(sources.filter(file => file !== "lib/auth/sign-out.ts" && read(file).includes("signOutEverywhere(")).length >= (admin ? 1 : 2), "the layout shells must use signOutEverywhere")

  // The proxy only forwards plain paths under /api/v1/ and never attaches the
  // bearer token to anything else.
  const forwarded = []
  globalThis.fetch = async (url, init) => {
    forwarded.push({ url, authorization: new Headers(init?.headers).get("authorization") })
    return Response.json({ ok: true })
  }
  const allowed = [[["users", "me"], "/api/v1/users/me"], [["health"], "/actuator/health"], [["files", "a b"], "/api/v1/files/a%20b"]]
  for (const [segments, expected] of allowed) {
    forwarded.length = 0
    const response = await route.GET(await request(live), { params: { path: segments } })
    assert.equal(response.status, 200, `allowed path ${segments} must be forwarded`)
    assert.deepEqual(forwarded, [{ url: `${backend}${expected}`, authorization: "Bearer old-access" }])
    assert.equal(apiRoutes.resolveProxyPath(segments), expected)
  }
  const rejectedPaths = [
    [".."], ["."], ["users", "..", "..", "actuator", "env"], ["..", "..", "actuator", "health"],
    ["%2e%2e"], ["%2E%2E", "x"], ["users", "%2e%2e", "%2e%2e", "actuator"], ["%252e%252e"], ["..%2fadmin"], ["users%2F..%2Fadmin"], ["users", "%5c..%5cadmin"],
    ["https:", "", "evil.example"], ["https://evil.example/x"], ["https%3A%2F%2Fevil.example"], ["//evil.example"], ["mailto:x@evil.example"],
    ["users", ""], [""], ["a;b"], ["bad%"], ["nul\u0000"], [], null,
  ]
  for (const segments of rejectedPaths) {
    forwarded.length = 0
    assert.equal(apiRoutes.resolveProxyPath(segments), null, `resolveProxyPath must reject ${JSON.stringify(segments)}`)
    const response = await route.GET(await request(live), { params: { path: segments } })
    assert.equal(response.status, 400, `proxy must reject ${JSON.stringify(segments)}`)
    assert.deepEqual(await response.json(), { error: "Invalid API path" })
    assert.deepEqual(forwarded, [], "a rejected path must never reach the backend")
  }

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
    // Every login-page button must name a configured Auth.js provider: next-auth/react
    // sends an unknown id to the sign-in page instead of the provider.
    const providerIds = new Set(config.providers.map(entry => (typeof entry === "function" ? entry() : entry).id))
    const loginPage = fs.readFileSync(path.join(app, "app/[locale]/(public)/login/page.tsx"), "utf8")
    const methods = /const methods[^=]*=\s*\[([\s\S]*?)\r?\n\s*\]\r?\n/.exec(loginPage)
    assert.ok(methods, "login page must declare its social methods")
    const pageIds = [...methods[1].matchAll(/\bid:\s*"([^"]+)"/g)].map(match => match[1])
    assert.deepEqual([...pageIds].sort(), [...providerIds].filter(id => id !== "credentials").sort(), "login page methods must match the configured providers")
    for (const id of pageIds) assert.ok(providerIds.has(id), `login page uses unknown provider id ${id}`)
    assert.ok(/signIn\(method[,)]/.test(loginPage), "login page must sign in with the method id")
    assert.equal(providerIds.has("credentials"), loginPage.includes('signIn("credentials"'), "credentials form must match the credentials provider")
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
  console.log(`PASS: ${path.basename(app)} encrypted cookies, refresh persistence, concurrency, rejection, outages, public session, admission, sign-out revocation, provider ids and proxy path confinement checks`)
} finally { globalThis.fetch = originalFetch }
