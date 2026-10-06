/** @type {import("next").NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  turbopack: {
    // The app is one folder of a larger repository: keep the build inside it.
    root: import.meta.dirname,
  },
}

export default nextConfig
