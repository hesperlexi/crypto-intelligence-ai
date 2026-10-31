/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: Object.fromEntries(
        ["ink", "panel", "raised", "line", "text", "mute", "bull", "bear", "warn", "accent", "glass", "ai"]
          .map((c) => [c, `rgb(var(--${c}) / <alpha-value>)`]),
      ),
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        display: ["Sora", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        // no web mono font is loaded (JetBrains Mono was declared but never fetched): system monospace only
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
