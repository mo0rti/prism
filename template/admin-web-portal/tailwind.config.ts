import type { Config } from "tailwindcss"

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        accent: "hsl(var(--accent))",
        panel: "hsl(var(--panel))",
        foreground: "hsl(var(--foreground))",
      },
      borderRadius: {
        xl: "1rem",
      },
    },
  },
  plugins: [],
}

export default config
