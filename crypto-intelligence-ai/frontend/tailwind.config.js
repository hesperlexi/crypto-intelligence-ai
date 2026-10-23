/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#080b10",
        panel: "#0e131a",
        raised: "#141b24",
        line: "#1e2835",
        text: "#cdd6e1",
        mute: "#6f7e91",
        bull: "#2ebd85",
        bear: "#f0506e",
        warn: "#e8b339",
        accent: "#5aa0ff",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
