/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "rgb(var(--brand-500) / <alpha-value>)",
          50: "rgb(var(--brand-50) / <alpha-value>)",
          100: "rgb(var(--brand-100) / <alpha-value>)",
          200: "rgb(var(--brand-200) / <alpha-value>)",
          300: "rgb(var(--brand-300) / <alpha-value>)",
          400: "rgb(var(--brand-400) / <alpha-value>)",
          500: "rgb(var(--brand-500) / <alpha-value>)",
          600: "rgb(var(--brand-600) / <alpha-value>)",
          700: "rgb(var(--brand-700) / <alpha-value>)",
          800: "rgb(var(--brand-800) / <alpha-value>)",
          900: "rgb(var(--brand-900) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent-500) / <alpha-value>)",
          50: "rgb(var(--accent-50) / <alpha-value>)",
          100: "rgb(var(--accent-100) / <alpha-value>)",
          200: "rgb(var(--accent-200) / <alpha-value>)",
          300: "rgb(var(--accent-300) / <alpha-value>)",
          400: "rgb(var(--accent-400) / <alpha-value>)",
          500: "rgb(var(--accent-500) / <alpha-value>)",
          600: "rgb(var(--accent-600) / <alpha-value>)",
          700: "rgb(var(--accent-700) / <alpha-value>)",
        },
        ok: { DEFAULT: "rgb(var(--ok-500) / <alpha-value>)", 50: "rgb(var(--ok-50) / <alpha-value>)", 500: "rgb(var(--ok-500) / <alpha-value>)", 600: "rgb(var(--ok-600) / <alpha-value>)" },
        bad: { DEFAULT: "rgb(var(--bad-500) / <alpha-value>)", 50: "rgb(var(--bad-50) / <alpha-value>)", 500: "rgb(var(--bad-500) / <alpha-value>)", 600: "rgb(var(--bad-600) / <alpha-value>)" },
        warn: { DEFAULT: "rgb(var(--warn-500) / <alpha-value>)", 50: "rgb(var(--warn-50) / <alpha-value>)", 500: "rgb(var(--warn-500) / <alpha-value>)", 600: "rgb(var(--warn-600) / <alpha-value>)" },
        surface: {
          DEFAULT: "rgb(var(--surface-default) / <alpha-value>)",
          secondary: "rgb(var(--surface-secondary) / <alpha-value>)",
          tertiary: "rgb(var(--surface-tertiary) / <alpha-value>)",
          chat: "rgb(var(--surface-chat) / <alpha-value>)",
        },
        line: { DEFAULT: "rgb(var(--line-default) / <alpha-value>)", subtle: "rgb(var(--line-subtle) / <alpha-value>)" },
        ink: "rgb(var(--ink-default) / <alpha-value>)",
        muted: "rgb(var(--muted-default) / <alpha-value>)",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"SF Pro Text"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          '"Segoe UI"',
          "sans-serif",
        ],
        display: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"SF Pro Display"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: { sm: "8px", md: "10px", lg: "14px", xl: "18px" },
      boxShadow: {
        card: "0 1px 2px rgb(var(--shadow-rgb) / 0.05), 0 2px 8px -2px rgb(var(--shadow-rgb) / 0.06)",
        elevated:
          "0 2px 4px rgb(var(--shadow-rgb) / 0.05), 0 8px 24px -6px rgb(var(--shadow-rgb) / 0.12)",
        pop: "0 4px 12px rgb(var(--shadow-rgb) / 0.08), 0 16px 40px -12px rgb(var(--shadow-rgb) / 0.18)",
      },
      letterSpacing: { tightish: "-0.02em" },
      transitionTimingFunction: {
        expo: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
      animation: {
        breathe: "breathe 2.4s ease-in-out infinite",
        typing: "typing 1.1s ease-in-out infinite",
        "fade-up": "fadeUp 0.5s cubic-bezier(0.22,1,0.36,1) both",
        "pulse-ring": "pulseRing 2s cubic-bezier(0.22,1,0.36,1) infinite",
      },
      keyframes: {
        breathe: {
          "0%, 100%": { transform: "scale(1)" },
          "50%": { transform: "scale(1.25)" },
        },
        typing: {
          "0%, 100%": { opacity: "0.35" },
          "50%": { opacity: "1" },
        },
        fadeUp: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        pulseRing: {
          "0%": { transform: "scale(1)", opacity: "0.5" },
          "100%": { transform: "scale(2.2)", opacity: "0" },
        },
      },
    },
  },
  plugins: [],
};
