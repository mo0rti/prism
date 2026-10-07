import createClient from "openapi-fetch"

import { apiBaseUrl } from "./config"
import type { paths } from "./generated/schema"

// The types come from the operations, not from schema names, so a renamed schema cannot break them.
export type UserProfile = paths["/api/me"]["get"]["responses"]["200"]["content"]["application/json"]
export type DevIdentityRequest = NonNullable<paths["/api/dev-identity/token"]["post"]["requestBody"]>["content"]["application/json"]

type FetchLike = (request: Request) => Promise<Response>

/**
 * The typed client of `shared/api-contracts/openapi.yml`. `openapi-typescript` generates its types
 * into `./generated/schema.d.ts` (`npm run generate:api`), so a path or a field that the contract
 * lacks fails the typecheck.
 */
export function createApiClient(options: { token?: string; fetch?: FetchLike } = {}) {
  return createClient<paths>({
    baseUrl: apiBaseUrl(),
    ...(options.fetch ? { fetch: options.fetch } : {}),
    ...(options.token ? { headers: { Authorization: `Bearer ${options.token}` } } : {}),
  })
}

export type CurrentUserResult = { status: number; user?: UserProfile }

/** `GET /api/me`: the profile of the signed-in user. */
export async function getCurrentUser(token: string, fetch?: FetchLike): Promise<CurrentUserResult> {
  const { data, response } = await createApiClient({ token, fetch }).GET("/api/me")
  return { status: response.status, user: data }
}

export type DevIdentityResult = { status: number; accessToken?: string; expiresIn?: number }

/** `POST /api/dev-identity/token`: a token of the backend's local development identity (the `local` profile only). */
export async function createDevIdentityToken(body: DevIdentityRequest = {}, fetch?: FetchLike): Promise<DevIdentityResult> {
  const { data, response } = await createApiClient({ fetch }).POST("/api/dev-identity/token", { body })
  return { status: response.status, accessToken: data?.accessToken, expiresIn: data?.expiresIn }
}
