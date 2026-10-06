import { defineCloudflareConfig } from "@opennextjs/cloudflare"

export default defineCloudflareConfig({
  // Uncomment to back the incremental cache with R2.
  // Import `r2IncrementalCache` from
  // `@opennextjs/cloudflare/overrides/incremental-cache/r2-incremental-cache`
  // when you enable it.
  // See https://opennext.js.org/cloudflare/caching
  // incrementalCache: r2IncrementalCache,
})
