/** The backend this app was generated for: the address of its local development run, which `API_BASE_URL` overrides. */
export const DEFAULT_API_BASE_URL = "http://localhost:8080"

/** The backend that serves the shared API contract. Server-side only: the browser never calls it. */
export function apiBaseUrl(): string {
  const configured = process.env.API_BASE_URL?.trim()
  return (configured || DEFAULT_API_BASE_URL).replace(/\/+$/, "")
}
