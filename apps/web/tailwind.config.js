/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#4f5bd5",
         50: "#eef0fb",
          100: "#e3e6f9",
          200: "#c7cdf2",
          300: "#a3acea",
          400: "#7b87df",
          500: "#4f5bd5",
          600: "#3f49bd",
          700: "#343c9a",
          800: "#2d337c",
          900: "#282c62",
        },
        accent: {
          DEFAULT: "#c23732",
          50: "#fbeceb",
          100: "#f7d9d7",
          200: "#eeb4b0",
          300: "#e28a85",
          400: "#d45e58",
          500: "#c23732",
          600: "#a62925",
          700: "#87211e",
        },
        ok: { DEFAULT: "#1e8e5f", 50: "#e7f5ee", 500: "#1e8e5f", 600: "#17714b" },
        bad: { DEFAULT: "#c4433c", 50: "#fbeceb", 500: "#c4433c", 600: "#a62f29" },
        warn: { DEFAULT: "#a6611a", 50: "#fbf2e3", 500: "#a6611a", 600: "#844b12" },
        surface: {
          DEFAULT: "#ffffff",
          secondary: "#f7f5f0",
          tertiary: "#fbfaf7",
          chat: "#f3f1eb",
        },
        line: { DEFAULT: "#e8e4db", subtle: "#f0ede5" },
        ink: "#201e1b",
        muted: "#706a5f",
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
        card: "0 1px 2px rgba(60, 50, 35, 0.05), 0 2px 8px -2px rgba(60, 50, 35, 0.06)",
        elevated:
          "0 2px 4px rgba(60, 50, 35, 0.05), 0 8px 24px -6px rgba(60, 50, 35, 0.12)",
        pop: "0 4px 12px rgba(60, 50, 35, 0.08), 0 16px 40px -12px rgba(60, 50, 35, 0.18)",
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
