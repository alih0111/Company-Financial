/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {},
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
