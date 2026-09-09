/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#4f6ef7",
          50: "#eef1fb",
          100: "#e8edff",
          200: "#c8d2f8",
          300: "#9aa8f0",
          400: "#6d83e8",
          500: "#4f6ef7",
          600: "#3a54d9",
          700: "#2d42b0",
          800: "#243588",
          900: "#1c2a6b",
        },
        ok: { DEFAULT: "#1fa971", 50: "#e4f7ee", 500: "#1fa971", 600: "#18794e" },
        bad: { DEFAULT: "#d6483f", 50: "#fdeaea", 500: "#d6483f", 600: "#b8322a" },
        warn: { DEFAULT: "#a15f12", 50: "#fff4e6", 500: "#a15f12" },
        surface: { DEFAULT: "#ffffff", secondary: "#f6f7fb", tertiary: "#fafbfe", chat: "#f2f3f8" },
        line: { DEFAULT: "#e6e8f0", subtle: "#f1f2f6" },
        ink: "#1f2333",
        muted: "#7a7f94",
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", '"PingFang SC"', '"Microsoft YaHei"', '"Segoe UI"', "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: { sm: "8px", md: "10px", lg: "14px", xl: "16px" },
      boxShadow: {
        card: "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)",
        elevated: "0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03)",
      },
      animation: {
        breathe: "breathe 2.4s ease-in-out infinite",
        typing: "typing 1.1s ease-in-out infinite",
      },
      keyframes: {
        breathe: { "0%, 100%": { transform: "scale(1)" }, "50%": { transform: "scale(1.25)" } },
        typing: { "0%, 100%": { opacity: "0.35" }, "50%": { opacity: "1" } },
      },
    },
  },
  plugins: [],
};
