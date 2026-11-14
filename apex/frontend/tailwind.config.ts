import type { Config } from "tailwindcss";
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0a0b0d", panel: "#121418", panel2: "#181b20", line: "#262a31", ink: "#f2f3f5", dim: "#a3a8b3", faint: "#6b717d",
        f1: "#e10600", good: "#2fbf71", warn: "#e0a100", bad: "#ff5a52",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "Liberation Mono", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
