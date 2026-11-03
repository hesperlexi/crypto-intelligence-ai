/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: Object.fromEntries(
        ["ink", "panel", "raised", "line", "text", "mute", "bull", "bear", "warn", "accent", "glass", "ai"]
          .map((c) => [c, `rgb(var(--${c}) / <alpha-value>)`]),
      ),
      // UI v2.15 type scale: 12 / 14 / 16 / 20 / 28 px (xs / sm / base / lg = xl / 2xl). Larger sizes are only for the
      // signed-out landing page and hero numbers.
      fontSize: {
        lg: ["1.25rem", { lineHeight: "1.75rem" }],
        "2xl": ["1.75rem", { lineHeight: "2.125rem" }],
      },
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
