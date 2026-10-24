/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Vazirmatn",
          "Segoe UI",
          "Tahoma",
          "system-ui",
          "-apple-system",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        "glow-emerald": "0 0 24px -6px rgba(16, 185, 129, 0.35)",
        "glow-indigo": "0 0 24px -6px rgba(99, 102, 241, 0.35)",
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -12px rgba(15, 23, 42, 0.12)",
        "card-hover":
          "0 2px 4px rgba(15, 23, 42, 0.05), 0 16px 40px -16px rgba(15, 23, 42, 0.22)",
      },
      transitionTimingFunction: {
        "out-expo": "cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [
    function ({ addUtilities }) {
      addUtilities({
        ".direction-rtl": {
          direction: "rtl",
        },
        ".direction-ltr": {
          direction: "ltr",
        },
      });
    },
  ],
};
