export const PATH_MAPPINGS: Record<string, string> = {
  "/api/v1/health": "/actuator/health",
}

export function getBackendPath(frontendPath: string): string {
  return PATH_MAPPINGS[frontendPath] ?? frontendPath
}
